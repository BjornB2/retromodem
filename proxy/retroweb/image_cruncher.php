<?php
/**
 * RetroWEB - Image Compression Endpoint
 */

require_once __DIR__ . '/config.php';

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
    $imageUrl = is_string($_GET['url']) ? trim($_GET['url']) : '';
} elseif (!empty($_SERVER['QUERY_STRING'])) {
    // Fallback: parse QUERY_STRING handmatig als $_GET niet werkt
    parse_str($_SERVER['QUERY_STRING'], $params);
    if (isset($params['url'])) {
        $imageUrl = is_string($params['url']) ? trim($params['url']) : '';
    }
}

$originalWidth = isset($_GET['w']) ? (int)$_GET['w'] : null;
$originalHeight = isset($_GET['h']) ? (int)$_GET['h'] : null;

if (empty($imageUrl)) {
    sendHttp10Response(204);
    setHttp10Headers(0);
    exit;
}

// Every hop is validated and pinned; no automatic redirect can reach LAN/loopback.
require_once __DIR__ . '/lib/ImageFetcher.php';
$fetcher = new RetroWebImageFetcher(MAX_IMAGE_PROCESSING_SIZE, 25000, 5, USER_AGENT);
$fetched = $fetcher->fetch($imageUrl);
if ($fetched['status'] !== 200) {
    sendHttp10Response($fetched['status']);
    setHttp10Headers(0);
    exit;
}
$imageData = $fetched['body'];
$imageUrl = $fetched['url'];

// Set timeout voor image processing
$timeout = defined('IMAGE_PROCESSING_TIMEOUT') ? IMAGE_PROCESSING_TIMEOUT : 30;
set_time_limit($timeout);

// Content type comes from the validated final response, never an old redirect.
$headers = ['content-type' => $fetched['type']];

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
                $maxWidth = MAX_IMAGE_WIDTH;
                $maxHeight = MAX_IMAGE_HEIGHT;
                $targetWidth = $maxWidth;
                $targetHeight = $maxHeight;
                
                if ($originalWidth !== null && $originalWidth > 0 && $originalWidth < $maxWidth) {
                    $targetWidth = $originalWidth;
                }
                
                // Calculate resize ratio
                $ratio = min($targetWidth / $actualWidth, $targetHeight / $actualHeight);
                
                if ($ratio < 1.0) {
                    $newWidth = (int)($actualWidth * $ratio);
                    $newHeight = (int)($actualHeight * $ratio);
                    $imagick->resizeImage($newWidth, $newHeight, Imagick::FILTER_LANCZOS, 1);
                } else {
                    $newWidth = $actualWidth;
                    $newHeight = $actualHeight;
                }
                
                // Convert to GIF
                $imagick->setImageFormat('gif');
                
                sendHttp10Response(200);
                header('Content-Type: image/gif');
                $imageBlob = $imagick->getImageBlob();
                setHttp10Headers(strlen($imageBlob));
                echo $imageBlob;
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
    $maxWidth = MAX_IMAGE_WIDTH;
    $maxHeight = MAX_IMAGE_HEIGHT;
    $targetWidth = $maxWidth;
    $targetHeight = $maxHeight;
    
    if ($originalWidth !== null && $originalWidth > 0 && $originalWidth < $maxWidth) {
        $targetWidth = $originalWidth;
    }
    
    // Calculate resize ratio (avoid division by zero)
    if ($svgWidth > 0 && $svgHeight > 0) {
        $ratio = min($targetWidth / $svgWidth, $targetHeight / $svgHeight);
        
        if ($ratio < 1.0) {
            $newWidth = (int)($svgWidth * $ratio);
            $newHeight = (int)($svgHeight * $ratio);
        } else {
            $newWidth = min($svgWidth, $maxWidth);
            $newHeight = min($svgHeight, $maxHeight);
        }
    } else {
        // Fallback to default if dimensions couldn't be determined
        $newWidth = min(300, $maxWidth);
        $newHeight = min(300, $maxHeight);
    }
    
    // Ensure minimum size for placeholder
    if ($newWidth < 50) {
        $newWidth = 50;
    }
    if ($newHeight < 50) {
        $newHeight = 50;
    }
    
    // Create a simple placeholder image (white background with text)
    $placeholder = @imagecreatetruecolor($newWidth, $newHeight);
    if ($placeholder === false) {
        // If creation failed, use default size
        $placeholder = imagecreatetruecolor(300, 300);
        $newWidth = 300;
        $newHeight = 300;
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
    
    sendHttp10Response(200);
    header('Content-Type: image/gif');
    ob_start();
    imagegif($placeholder);
    $imageData = ob_get_clean();
    setHttp10Headers(strlen($imageData));
    echo $imageData;
    imagedestroy($placeholder);
    exit;
}

// Detect image type
$imageType = null;
$imageResource = null;

// Probeer image te laden
if (function_exists('imagecreatefromstring')) {
    $imageResource = @imagecreatefromstring($imageData);
    if ($imageResource !== false) {
        // Detect type via getimagesizefromstring
        $imageInfo = @getimagesizefromstring($imageData);
        if ($imageInfo !== false) {
            $imageType = $imageInfo[2]; // IMAGETYPE_JPEG, IMAGETYPE_PNG, etc.
        }
    }
}

// Fallback: check Content-Type header
if ($imageType === null && isset($headers['content-type'])) {
    $contentType = strtolower($headers['content-type']);
    if (strpos($contentType, 'jpeg') !== false || strpos($contentType, 'jpg') !== false) {
        $imageResource = @imagecreatefromjpeg('data://image/jpeg;base64,' . base64_encode($imageData));
        if ($imageResource !== false) {
            $imageType = IMAGETYPE_JPEG;
        }
    } elseif (strpos($contentType, 'png') !== false) {
        $imageResource = @imagecreatefrompng('data://image/png;base64,' . base64_encode($imageData));
        if ($imageResource !== false) {
            $imageType = IMAGETYPE_PNG;
        }
    } elseif (strpos($contentType, 'gif') !== false) {
        $imageResource = @imagecreatefromgif('data://image/gif;base64,' . base64_encode($imageData));
        if ($imageResource !== false) {
            $imageType = IMAGETYPE_GIF;
        }
    } elseif (strpos($contentType, 'webp') !== false && function_exists('imagecreatefromwebp')) {
        $imageResource = @imagecreatefromwebp('data://image/webp;base64,' . base64_encode($imageData));
        if ($imageResource !== false) {
            $imageType = IMAGETYPE_WEBP;
        }
    } elseif (strpos($contentType, 'bmp') !== false || strpos($contentType, 'x-ms-bmp') !== false) {
        $imageResource = @imagecreatefrombmp('data://image/bmp;base64,' . base64_encode($imageData));
        if ($imageResource !== false) {
            $imageType = IMAGETYPE_BMP;
        }
    }
}

// Als nog steeds geen image, probeer direct
if ($imageResource === false) {
    // Probeer als JPEG
    $imageResource = @imagecreatefromjpeg('data://image/jpeg;base64,' . base64_encode($imageData));
    if ($imageResource !== false) {
        $imageType = IMAGETYPE_JPEG;
    } else {
        // Probeer als PNG
        $imageResource = @imagecreatefrompng('data://image/png;base64,' . base64_encode($imageData));
        if ($imageResource !== false) {
            $imageType = IMAGETYPE_PNG;
        } else {
            // Probeer als GIF
            $imageResource = @imagecreatefromgif('data://image/gif;base64,' . base64_encode($imageData));
            if ($imageResource !== false) {
                $imageType = IMAGETYPE_GIF;
            } else {
                // Probeer als WebP (PHP 7.1+)
                if (function_exists('imagecreatefromwebp')) {
                    $imageResource = @imagecreatefromwebp('data://image/webp;base64,' . base64_encode($imageData));
                    if ($imageResource !== false) {
                        $imageType = IMAGETYPE_WEBP;
                    }
                }
                // Probeer als BMP
                if ($imageResource === false && function_exists('imagecreatefrombmp')) {
                    $imageResource = @imagecreatefrombmp('data://image/bmp;base64,' . base64_encode($imageData));
                    if ($imageResource !== false) {
                        $imageType = IMAGETYPE_BMP;
                    }
                }
            }
        }
    }
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

// Bereken nieuwe dimensies - simpele logica
// Max dimensies zijn 300x300
$maxWidth = MAX_IMAGE_WIDTH;  // 300
$maxHeight = MAX_IMAGE_HEIGHT; // 300

// Als originele dimensions opgegeven zijn EN kleiner dan max, gebruik die
// Anders gebruik max (300x300)
$targetWidth = $maxWidth;
$targetHeight = $maxHeight;

if ($originalWidth !== null && $originalWidth > 0 && $originalWidth < $maxWidth) {
    $targetWidth = $originalWidth;
}
if ($originalHeight !== null && $originalHeight > 0 && $originalHeight < $maxHeight) {
    $targetHeight = $originalHeight;
}

// Bereken nieuwe dimensies met aspect ratio behoud
// Zorg dat image niet groter wordt dan targetWidth x targetHeight
$ratio = min($targetWidth / $actualWidth, $targetHeight / $actualHeight);

if ($ratio >= 1.0) {
    // Image is al kleiner of gelijk aan target, gebruik originele dimensies
    $newWidth = $actualWidth;
    $newHeight = $actualHeight;
} else {
    // Resize naar target dimensies met aspect ratio behoud
    $newWidth = (int)($actualWidth * $ratio);
    $newHeight = (int)($actualHeight * $ratio);
    
    // Safety check: nooit groter dan max
    if ($newWidth > $maxWidth) {
        $newWidth = $maxWidth;
        $newHeight = (int)($maxWidth / $actualWidth * $actualHeight);
    }
    if ($newHeight > $maxHeight) {
        $newHeight = $maxHeight;
        $newWidth = (int)($maxHeight / $actualHeight * $actualWidth);
    }
}

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
sendHttp10Response(200);
header('Content-Type: image/gif');
ob_start();
imagegif($newImage);
$imageData = ob_get_clean();
setHttp10Headers(strlen($imageData));
echo $imageData;

// Cleanup
imagedestroy($imageResource);
imagedestroy($newImage);
exit;
