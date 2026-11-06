<?php
/**
 * RetroWEB - Image Compression Endpoint
 */

require_once __DIR__ . '/config.php';
require_once __DIR__ . '/lib/ImageCache.php';
require_once __DIR__ . '/lib/SecureHttpClient.php';

// Initialiseer error handling
initErrorHandling();

// Stel security headers in
setSecurityHeaders();

// Check request size
if (!checkRequestSize()) {
    sendHttp10Response(413);
    setHttp10Headers(0);
    exit;
}

// Rate limiting
if (!checkRateLimit()) {
    exit; // checkRateLimit() heeft al error response gestuurd
}

// Haal URL parameter op (met fallback voor HTTP/1.0 browsers)
$imageUrl = '';
if (isset($_GET['url'])) {
    $imageUrl = trim($_GET['url']);
} elseif (!empty($_SERVER['QUERY_STRING'])) {
    // Fallback: parse QUERY_STRING handmatig als $_GET niet werkt
    parse_str($_SERVER['QUERY_STRING'], $params);
    if (isset($params['url'])) {
        $imageUrl = trim($params['url']);
    }
}

$activeSettings = getUserSettings();
registerAggregateProcessing('image', $activeSettings['resolved_profile']);
$originalWidth = isset($_GET['w']) ? (int)$_GET['w'] : null;
$originalHeight = isset($_GET['h']) ? (int)$_GET['h'] : null;

if (empty($imageUrl)) {
    sendHttp10Response(204);
    setHttp10Headers(0);
    exit;
}

// Soepelere URL validatie: gebruik regex in plaats van filter_var
// filter_var kan te strikt zijn voor HTTP/1.0 browsers
if (!preg_match('/^https?:\/\/[a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,}/', $imageUrl)) {
    sendHttp10Response(204);
    setHttp10Headers(0);
    exit;
}

// SSRF bescherming: check of URL naar intern/private netwerk verwijst
if (isInternalUrl($imageUrl)) {
    logSecurityEvent('ssrf_attempt_image', ['url' => $imageUrl, 'ip' => getClientIp()]);
    sendHttp10Response(403);
    setHttp10Headers(0);
    exit;
}

// Sanitize URL
$imageUrl = sanitizeUrl($imageUrl);
if ($imageUrl === false) {
    logSecurityEvent('invalid_url_format_image', ['url' => isset($_GET['url']) ? substr($_GET['url'], 0, 200) : '']);
    sendHttp10Response(204);
    setHttp10Headers(0);
    exit;
}

$imageCache = new \RetroWEB\ImageCache(
    CACHE_DIR . '/images', IMAGE_CACHE_TTL, IMAGE_CACHE_MAX_FILES, IMAGE_CACHE_MAX_BYTES
);
$imageCacheKey = $imageCache->key([
    'version'=>CACHE_VERSION, 'url'=>$imageUrl,
    'max_width'=>$activeSettings['image_width'], 'max_height'=>$activeSettings['image_height'],
    'hint_width'=>$originalWidth, 'hint_height'=>$originalHeight,
    'palette'=>GIF_PALETTE_COLORS, 'dithering'=>GIF_USE_DITHERING,
]);
$cachedImage = $imageCache->get($imageCacheKey);
$cachedMetadata = $imageCache->metadata($imageCacheKey);
$sendCached = function(string $data, string $status): void {
    sendHttp10Response(200);
    header('Content-Type: image/gif');
    header('X-RetroWEB-Image-Cache: ' . $status);
    setHttp10Headers(strlen($data));
    echo $data;
};
if ($cachedImage !== null && (int)($cachedMetadata['checked_at'] ?? 0) >= time() - IMAGE_CACHE_REVALIDATE) {
    $sendCached($cachedImage, 'HIT');
    exit;
}
$imageCache->maybePrune();

$sourceMetadata = [];
$sendGif = function(string $data) use ($imageCache, $imageCacheKey, &$sourceMetadata): void {
    $imageCache->put($imageCacheKey, $data, $sourceMetadata);
    sendHttp10Response(200);
    header('Content-Type: image/gif');
    header('X-RetroWEB-Image-Cache: MISS');
    setHttp10Headers(strlen($data));
    echo $data;
};

// Fetch external images through the same DNS-pinned, redirect-validating
// transport as HTML. Every redirect is checked again before connecting.
$requestHeaders = [];
if ($cachedImage !== null && !empty($cachedMetadata['etag'])) $requestHeaders['If-None-Match'] = $cachedMetadata['etag'];
if ($cachedImage !== null && !empty($cachedMetadata['last_modified'])) $requestHeaders['If-Modified-Since'] = $cachedMetadata['last_modified'];
try {
    $imageResponse = \RetroWEB\SecureHttpClient::request(
        $imageUrl, 'GET', null, $requestHeaders, MAX_IMAGE_PROCESSING_SIZE, MAX_REDIRECT_DEPTH
    );
    $imageData = $imageResponse['data'];
    $responseHeaders = $imageResponse['headers'];
    $statusCode = $imageResponse['status'];
    $imageUrl = $imageResponse['url'];
} catch (Throwable $error) {
    error_log('Secure image fetch failed: ' . sanitizeLogMessage($error->getMessage()));
    $imageData = false; $responseHeaders = []; $statusCode = 0;
}

if ($cachedImage !== null && $statusCode === 304) {
    $cachedMetadata['checked_at'] = time();
    $imageCache->putMetadata($imageCacheKey, $cachedMetadata);
    $sendCached($cachedImage, 'REVALIDATED');
    exit;
}

if ($imageData === false || empty($imageData)) {
    if ($cachedImage !== null) {
        $sendCached($cachedImage, 'STALE');
        exit;
    }
    sendHttp10Response(204);
    setHttp10Headers(0);
    exit;
}

$sourceMetadata = ['checked_at'=>time(), 'source_hash'=>hash('sha256', $imageData)];
foreach ($responseHeaders as $header) {
    if (preg_match('/^ETag:\s*(.+)$/i', $header, $match)) $sourceMetadata['etag'] = trim($match[1]);
    if (preg_match('/^Last-Modified:\s*(.+)$/i', $header, $match)) $sourceMetadata['last_modified'] = trim($match[1]);
}
if ($cachedImage !== null && !empty($cachedMetadata['source_hash'])
    && hash_equals((string)$cachedMetadata['source_hash'], $sourceMetadata['source_hash'])) {
    $imageCache->putMetadata($imageCacheKey, $sourceMetadata);
    $sendCached($cachedImage, 'REVALIDATED');
    exit;
}

// Valideer Content-Length header
if (!validateContentLength($imageData, $responseHeaders)) {
    logSecurityEvent('content_length_mismatch_image', ['url' => $imageUrl]);
    // Log maar blokkeer niet - image kan nog steeds geldig zijn
}

// Check image size voor processing
if (strlen($imageData) > MAX_IMAGE_PROCESSING_SIZE) {
    logSecurityEvent('image_size_exceeded', ['size' => strlen($imageData), 'max' => MAX_IMAGE_PROCESSING_SIZE, 'url' => $imageUrl]);
    sendHttp10Response(413);
    setHttp10Headers(0);
    exit;
}

// Set timeout voor image processing
$timeout = defined('IMAGE_PROCESSING_TIMEOUT') ? IMAGE_PROCESSING_TIMEOUT : 30;
set_time_limit($timeout);

// Check Content-Type via response headers
$headers = [];
foreach ($responseHeaders as $header) {
        if (preg_match('/^Content-Type:\s*(.+)$/i', $header, $matches)) {
            $headers['content-type'] = strtolower(trim(explode(';', $matches[1])[0]));
        }
}

// Check if this is an SVG file (by Content-Type, file extension, or content)
$isSvg = false;

// Check Content-Type header
if (isset($headers['content-type']) && (strpos($headers['content-type'], 'svg') !== false || strpos($headers['content-type'], 'image/svg') !== false)) {
    $isSvg = true;
}

// Check file extension (more flexible pattern)
if (!$isSvg && preg_match('/\.svg(\?|#|$)/i', $imageUrl)) {
    $isSvg = true;
}

// Check content - look for SVG XML markers
if (!$isSvg) {
    $trimmedData = trim($imageData);
    // Check for SVG start tags (various formats)
    if (substr($trimmedData, 0, 5) === '<svg ' || 
        substr($trimmedData, 0, 4) === '<svg' ||
        substr($trimmedData, 0, 9) === '<?xml ver' ||
        strpos($trimmedData, '<svg') !== false ||
        strpos($trimmedData, 'xmlns="http://www.w3.org/2000/svg"') !== false ||
        strpos($trimmedData, "xmlns='http://www.w3.org/2000/svg'") !== false) {
        $isSvg = true;
    }
}

// Handle SVG files - convert to PNG/JPG using ImageMagick or fallback
if ($isSvg) {
    // Try ImageMagick first (best option)
    if (extension_loaded('imagick') && class_exists('Imagick')) {
        try {
            $imagick = new Imagick();
            $imagick->setBackgroundColor(new ImagickPixel('white'));
            $imagick->readImageBlob($imageData);
            $imagick->setImageFormat('png');
            
            // Get dimensions
            $actualWidth = $imagick->getImageWidth();
            $actualHeight = $imagick->getImageHeight();
            
            if ($actualWidth > 0 && $actualHeight > 0) {
                // Calculate target dimensions
                $maxWidth = max(1, $activeSettings['image_width']);
                $maxHeight = max(1, $activeSettings['image_height']);
                [$newWidth, $newHeight] = calculateDownscaledDimensions(
                    $actualWidth, $actualHeight, $maxWidth, $maxHeight, $originalWidth, $originalHeight
                );

                if ($newWidth !== $actualWidth || $newHeight !== $actualHeight) {
                    $imagick->resizeImage($newWidth, $newHeight, Imagick::FILTER_LANCZOS, 1);
                }
                
                // Convert to GIF
                $imagick->setImageFormat('gif');
                
                $imageBlob = $imagick->getImageBlob();
                $sendGif($imageBlob);
                $imagick->destroy();
                exit;
            }
        } catch (Exception $e) {
            // ImageMagick failed, try fallback
            error_log("ImageMagick SVG conversion failed: " . $e->getMessage());
        }
    }
    
    // Fallback: Try to extract dimensions from SVG and create a placeholder
    $svgWidth = 300;
    $svgHeight = 300;
    
    // Try to extract width/height from SVG (check multiple patterns)
    if (preg_match('/width\s*=\s*["\']?(\d+)/i', $imageData, $widthMatch)) {
        $svgWidth = (int)$widthMatch[1];
    } elseif (preg_match('/width\s*:\s*(\d+)/i', $imageData, $widthMatch)) {
        $svgWidth = (int)$widthMatch[1];
    }
    
    if (preg_match('/height\s*=\s*["\']?(\d+)/i', $imageData, $heightMatch)) {
        $svgHeight = (int)$heightMatch[1];
    } elseif (preg_match('/height\s*:\s*(\d+)/i', $imageData, $heightMatch)) {
        $svgHeight = (int)$heightMatch[1];
    }
    
    // Try viewBox as fallback
    if (($svgWidth === 300 || $svgHeight === 300) && preg_match('/viewBox\s*=\s*["\']?\s*\d+\s+\d+\s+(\d+)\s+(\d+)/i', $imageData, $viewBoxMatch)) {
        if ($svgWidth === 300) {
            $svgWidth = (int)$viewBoxMatch[1];
        }
        if ($svgHeight === 300) {
            $svgHeight = (int)$viewBoxMatch[2];
        }
    }
    
    // Ensure minimum dimensions
    if ($svgWidth <= 0) {
        $svgWidth = 300;
    }
    if ($svgHeight <= 0) {
        $svgHeight = 300;
    }
    
    // Calculate target dimensions
    $maxWidth = max(1, $activeSettings['image_width']);
    $maxHeight = max(1, $activeSettings['image_height']);
    if ($svgWidth > 0 && $svgHeight > 0) {
        [$newWidth, $newHeight] = calculateDownscaledDimensions(
            $svgWidth, $svgHeight, $maxWidth, $maxHeight, $originalWidth, $originalHeight
        );
    } else {
        // Fallback to default if dimensions couldn't be determined
        $newWidth = min(300, $maxWidth);
        $newHeight = min(300, $maxHeight);
    }
    
    // Create a simple placeholder image (white background with text)
    $placeholder = @imagecreatetruecolor($newWidth, $newHeight);
    if ($placeholder === false) {
        sendHttp10Response(204);
        setHttp10Headers(0);
        exit;
    }
    
    $white = imagecolorallocate($placeholder, 255, 255, 255);
    $black = imagecolorallocate($placeholder, 0, 0, 0);
    imagefill($placeholder, 0, 0, $white);
    
    // Add "SVG" text in the center
    $text = 'SVG';
    $fontSize = min(5, max(1, (int)($newWidth / 50)));
    $textWidth = strlen($text) * 6;
    $textX = max(0, (int)(($newWidth - $textWidth) / 2));
    $textY = max(0, (int)(($newHeight - 8) / 2));
    imagestring($placeholder, $fontSize, $textX, $textY, $text, $black);
    
    // Converteer truecolor naar palette voor GIF (configureerbaar aantal kleuren)
    $paletteColors = defined('GIF_PALETTE_COLORS') ? GIF_PALETTE_COLORS : 128;
    $useDithering = defined('GIF_USE_DITHERING') ? GIF_USE_DITHERING : true;
    imagetruecolortopalette($placeholder, $useDithering, $paletteColors);
    
    ob_start();
    imagegif($placeholder);
    $imageData = ob_get_clean();
    $sendGif($imageData);
    imagedestroy($placeholder);
    exit;
}

// Detect image type
$imageType = null;
$imageResource = false;

// Validate the bytes before invoking GD. Content-Type is only a hint and must
// never make us feed arbitrary HTML to every decoder or log a base64 payload.
$imageInfo = function_exists('getimagesizefromstring') ? @getimagesizefromstring($imageData) : false;
if ($imageInfo !== false && isset($imageInfo[2])) {
    $imageType = (int)$imageInfo[2];
    $imageResource = @imagecreatefromstring($imageData);
}

// Als nog steeds geen geldige image, retourneer 204
if ($imageResource === false || $imageType === null) {
    if ($imageResource !== false) {
        imagedestroy($imageResource);
    }
    sendHttp10Response(204);
    setHttp10Headers(0);
    exit;
}

// Ondersteunde image types: JPG, PNG, GIF, WebP, BMP
$supportedTypes = [IMAGETYPE_JPEG, IMAGETYPE_PNG, IMAGETYPE_GIF];
if (defined('IMAGETYPE_WEBP')) {
    $supportedTypes[] = IMAGETYPE_WEBP;
}
if (defined('IMAGETYPE_BMP')) {
    $supportedTypes[] = IMAGETYPE_BMP;
}

if (!in_array($imageType, $supportedTypes)) {
    imagedestroy($imageResource);
    sendHttp10Response(204);
    setHttp10Headers(0);
    exit;
}

// Haal originele dimensies op
$actualWidth = imagesx($imageResource);
$actualHeight = imagesy($imageResource);

if ($actualWidth === false || $actualHeight === false) {
    imagedestroy($imageResource);
    sendHttp10Response(204);
    setHttp10Headers(0);
    exit;
}

$maxWidth = max(1, $activeSettings['image_width']);
$maxHeight = max(1, $activeSettings['image_height']);
[$newWidth, $newHeight] = calculateDownscaledDimensions(
    $actualWidth, $actualHeight, $maxWidth, $maxHeight, $originalWidth, $originalHeight
);

// Check memory beschikbaarheid (ruwe schatting: 4 bytes per pixel)
$estimatedMemory = ($newWidth * $newHeight * 4) + (imagesx($imageResource) * imagesy($imageResource) * 4);
$memoryLimit = ini_get('memory_limit');
if ($memoryLimit !== '-1' && function_exists('parseMemoryLimit')) {
    $memoryLimitBytes = parseMemoryLimit($memoryLimit);
    $currentUsage = memory_get_usage(true);
    if (($currentUsage + $estimatedMemory) > ($memoryLimitBytes * 0.8)) {
        // Te weinig memory beschikbaar
        imagedestroy($imageResource);
        sendHttp10Response(500);
        setHttp10Headers(0);
        exit;
    }
}

// Maak nieuwe image resource
$newImage = imagecreatetruecolor($newWidth, $newHeight);

if ($newImage === false) {
    imagedestroy($imageResource);
    sendHttp10Response(204);
    setHttp10Headers(0);
    exit;
}

// Voor PNG, GIF, WebP en BMP: converteer naar JPG met witte achtergrond
if ($imageType === IMAGETYPE_PNG || $imageType === IMAGETYPE_GIF || 
    (defined('IMAGETYPE_WEBP') && $imageType === IMAGETYPE_WEBP) ||
    (defined('IMAGETYPE_BMP') && $imageType === IMAGETYPE_BMP)) {
    // Maak witte achtergrond
    $white = imagecolorallocate($newImage, 255, 255, 255);
    imagefill($newImage, 0, 0, $white);
    
    // Als image transparantie heeft, blend met witte achtergrond
    imagealphablending($newImage, true);
} else {
    // Voor JPG: gebruik witte achtergrond
    $white = imagecolorallocate($newImage, 255, 255, 255);
    imagefill($newImage, 0, 0, $white);
}

// Resize image
if ($newWidth != $actualWidth || $newHeight != $actualHeight) {
    // Resize nodig
    imagecopyresampled($newImage, $imageResource, 0, 0, 0, 0, $newWidth, $newHeight, $actualWidth, $actualHeight);
} else {
    // Geen resize nodig, kopieer direct
    imagecopy($newImage, $imageResource, 0, 0, 0, 0, $actualWidth, $actualHeight);
}

// Converteer truecolor naar palette voor GIF (configureerbaar aantal kleuren)
$paletteColors = defined('GIF_PALETTE_COLORS') ? GIF_PALETTE_COLORS : 128;
$useDithering = defined('GIF_USE_DITHERING') ? GIF_USE_DITHERING : true;
imagetruecolortopalette($newImage, $useDithering, $paletteColors);

// Output ALTIJD als GIF
ob_start();
imagegif($newImage);
$imageData = ob_get_clean();
$sendGif($imageData);

// Cleanup
imagedestroy($imageResource);
imagedestroy($newImage);
exit;
