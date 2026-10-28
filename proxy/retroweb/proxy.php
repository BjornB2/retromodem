<?php
/**
 * RetroWEB - Proxy endpoint voor het laden en vereenvoudigen van pagina's
 */

try {
    require_once __DIR__ . '/config.php';
} catch (Throwable $e) {
    error_log("Config load error: " . $e->getMessage() . "\n" . $e->getTraceAsString(), 3, __DIR__ . '/error.log');
    sendHttp10Response(500);
    exit;
}

// Initialiseer error handling
initErrorHandling();

// Stel security headers in
setSecurityHeaders();

// Check request size
if (!checkRequestSize()) {
    sendHttp10Response(413);
    $errorHtml = "<html><head><title>Request Too Large</title></head><body>\n";
    $errorHtml .= renderNavigation(getImageMode());
    $errorHtml .= "<h1>413 Request Entity Too Large</h1>\n";
    $errorHtml .= "<p>Request size exceeds maximum allowed size.</p>\n";
    $errorHtml .= "</body></html>\n";
    setHttp10Headers(strlen($errorHtml));
    echo $errorHtml;
    exit;
}

// Rate limiting
if (!checkRateLimit()) {
    exit; // checkRateLimit() heeft al error response gestuurd
}

require_once __DIR__ . '/lib/PagePaginator.php';
$pageSize = $_GET['page_size'] ?? getenv('RETROMODEM_PROXY_PAGE_SIZE');
$pageImages = $_GET['page_images'] ?? getenv('RETROMODEM_PROXY_PAGE_IMAGES');
$pageSize = is_string($pageSize) && in_array($pageSize, ['0', '12000', '18000', '25000', '50000', '75000', '100000', '125000', '150000', '175000', '200000'], true) ? (int)$pageSize : 18000;
$pageImages = is_string($pageImages) && preg_match('/^(?:[0-9]|10)$/D', $pageImages) ? (int)$pageImages : 5;
$pagePaginator = new RetroWebPagePaginator(CACHE_DIR . '/pages', $pageSize, $pageImages);
// Snapshot navigation is local and must not fetch the original site again.
// Handle it before requiring an origin URL or loading the content extractor.
if (isset($_GET['document'])) {
    $document = is_string($_GET['document']) ? $_GET['document'] : '';
    $part = isset($_GET['part']) ? (is_string($_GET['part']) ? $_GET['part'] : '') : '1';
    $selectedPage = $pagePaginator->read($document, $part);
    sendHttp10Response($selectedPage['status']);
    header('Content-Type: text/html; charset=iso-8859-1');
    setHttp10Headers(strlen($selectedPage['html']));
    echo $selectedPage['html'];
    exit;
}

try {
    require_once __DIR__ . '/vendor/autoload.php';
} catch (Throwable $e) {
    error_log("Autoload error: " . $e->getMessage() . "\n" . $e->getTraceAsString(), 3, __DIR__ . '/error.log');
    sendHttp10Response(500);
    exit;
}

// Content extractor wordt via config.php geladen

// Haal URL parameter op (met fallback voor HTTP/1.0 browsers)
$targetUrl = '';
if (isset($_GET['url'])) {
    $targetUrl = trim($_GET['url']);
} elseif (!empty($_SERVER['QUERY_STRING'])) {
    // Fallback: parse QUERY_STRING handmatig als $_GET niet werkt
    parse_str($_SERVER['QUERY_STRING'], $params);
    if (isset($params['url'])) {
        $targetUrl = trim($params['url']);
    }
}

$imageMode = getImageMode();
$baseUrl = getBaseUrl();

// Track bezoeker en pageview
trackVisitor();

if (empty($targetUrl)) {
    sendHttp10Response(400);
    $errorHtml = "<html><head><title>Error</title></head><body>\n";
    $errorHtml .= renderNavigation($imageMode);
    $errorHtml .= "<h1>Error</h1>\n";
    $errorHtml .= "<p>No URL specified. Use: <code>proxy.php?url=https://example.com</code></p>\n";
    $errorHtml .= "</body></html>\n";
    setHttp10Headers(strlen($errorHtml));
    echo $errorHtml;
    exit;
}

// Voeg https:// toe als protocol ontbreekt (voor HTTP/1.0 browsers)
if (!preg_match('/^https?:\/\//', $targetUrl)) {
    // Check of het een domain lijkt te zijn (soepelere regex)
    if (preg_match('/^[a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,}/', $targetUrl)) {
        $targetUrl = 'https://' . $targetUrl;
    } else {
        // Geen geldige URL
        sendHttp10Response(400);
        $errorHtml = "<html><head><title>Error</title></head><body>\n";
        $errorHtml .= renderNavigation($imageMode);
        $errorHtml .= "<h1>Error</h1>\n";
        $errorHtml .= "<p>Invalid URL: " . htmlspecialchars($targetUrl) . "</p>\n";
        $errorHtml .= "</body></html>\n";
        setHttp10Headers(strlen($errorHtml));
        echo $errorHtml;
        exit;
    }
}

// Soepelere URL validatie: gebruik regex in plaats van filter_var
// filter_var kan te strikt zijn voor HTTP/1.0 browsers met encoding verschillen
if (!preg_match('/^https?:\/\/[a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,}/', $targetUrl)) {
    sendHttp10Response(400);
    $errorHtml = "<html><head><title>Error</title></head><body>\n";
    $errorHtml .= renderNavigation($imageMode);
    $errorHtml .= "<h1>Error</h1>\n";
    $errorHtml .= "<p>Ongeldige URL: " . htmlspecialchars($targetUrl) . "</p>\n";
    $errorHtml .= "</body></html>\n";
    setHttp10Headers(strlen($errorHtml));
    echo $errorHtml;
    exit;
}

// SSRF bescherming: check of URL naar intern/private netwerk verwijst
if (isInternalUrl($targetUrl)) {
    logSecurityEvent('ssrf_attempt', ['url' => $targetUrl, 'ip' => getClientIp()]);
    sendHttp10Response(403);
    $errorHtml = "<html><head><title>Forbidden</title></head><body>\n";
    $errorHtml .= renderNavigation($imageMode);
    $errorHtml .= "<h1>Forbidden</h1>\n";
    $errorHtml .= "<p>Access to internal URLs is not allowed.</p>\n";
    $errorHtml .= "</body></html>\n";
    setHttp10Headers(strlen($errorHtml));
    echo $errorHtml;
    exit;
}

// Sanitize URL
$targetUrl = sanitizeUrl($targetUrl);
if ($targetUrl === false) {
    logSecurityEvent('invalid_url_format', ['url' => isset($_GET['url']) ? substr($_GET['url'], 0, 200) : '']);
    sendHttp10Response(400);
    $errorHtml = "<html><head><title>Error</title></head><body>\n";
    $errorHtml .= renderNavigation($imageMode);
    $errorHtml .= "<h1>Error</h1>\n";
    $errorHtml .= "<p>Invalid URL format.</p>\n";
    $errorHtml .= "</body></html>\n";
    setHttp10Headers(strlen($errorHtml));
    echo $errorHtml;
    exit;
}

// Fetch once: retain cookies and use the same response for type detection and extraction.
require_once __DIR__ . '/upstream.php';
$upstream = fetchModemUpstream($targetUrl);
$targetUrl = $upstream['url'];
$contentType = $upstream['type'];
$prefetchedContent = $upstream['body'];
$upstreamProblem = modemUpstreamProblem($upstream);
if ($upstreamProblem !== null) {
    $page = '<html><head><title>Website niet beschikbaar</title></head><body><h1>Website niet beschikbaar</h1><p>'
        . htmlspecialchars($upstreamProblem) . '</p><p>Webadres: ' . htmlspecialchars($targetUrl)
        . '</p><p>Probeer het later opnieuw. Deze browser kan geen JavaScript-controle uitvoeren.</p></body></html>';
    sendHttp10Response(200);
    header('Content-Type: text/html; charset=iso-8859-1');
    setHttp10Headers(strlen($page));
    echo $page;
    exit;
}

// Check Content-Type via HEAD request (met fallback)
if (false) {
try {
    $headContext = createStreamContext('HEAD');
    $headHeaders = @get_headers($targetUrl, 1, $headContext);
    
    if ($headHeaders && is_array($headHeaders)) {
        // Normaliseer header keys naar lowercase
        $headers = [];
        foreach ($headHeaders as $key => $value) {
            if (is_numeric($key)) {
                // Numeric keys zijn response headers als strings
                if (preg_match('/^Content-Type:\s*(.+)$/i', $value, $matches)) {
                    $headers['content-type'] = strtolower(trim(explode(';', $matches[1])[0]));
                }
            } else {
                $headers[strtolower($key)] = $value;
            }
        }
        
        // Check Content-Type (kan array zijn bij redirects)
        if (isset($headers['content-type'])) {
            $contentType = is_array($headers['content-type']) 
                ? end($headers['content-type']) 
                : $headers['content-type'];
            $contentType = strtolower(trim(explode(';', $contentType)[0]));
        }
    }
} catch (Exception $e) {
    // Ignore errors bij HEAD request, we proberen het later met GET
    error_log('HEAD request failed: ' . $e->getMessage());
}

}
// Check of het een image is - redirect naar image_cruncher.php
$imageTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp', 'image/bmp', 'image/svg+xml'];
$isImage = false;

// Check op basis van Content-Type
if (!empty($contentType)) {
    $isImage = in_array($contentType, $imageTypes) || strpos($contentType, 'image/') === 0;
}

// Fallback: check op basis van file extension als Content-Type niet bekend is
if (!$isImage) {
    $path = parse_url($targetUrl, PHP_URL_PATH);
    if ($path) {
        $extension = strtolower(pathinfo($path, PATHINFO_EXTENSION));
        $imageExtensions = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg'];
        $isImage = in_array($extension, $imageExtensions);
    }
}

// Als het een image is, redirect naar image_cruncher.php
if ($isImage) {
    $encodedUrl = urlencode($targetUrl);
    sendHttp10Response(302);
    header('Location: ' . $baseUrl . '/image_cruncher.php?url=' . $encodedUrl);
    exit;
}

// Als niet HTML/plain text, stream als download
if (!empty($contentType) && $contentType !== 'text/html' && $contentType !== 'text/plain') {
    $getContext = createStreamContext('GET');
    $content = $prefetchedContent;
    
    // Valideer Content-Length voor download content
    $downloadHeaders = [];
    if (isset($http_response_header) && is_array($http_response_header)) {
        $downloadHeaders = $http_response_header;
    }
    if ($content !== false && !empty($content)) {
        if (!validateContentLength($content, $downloadHeaders)) {
            logSecurityEvent('content_length_mismatch_download', ['url' => $targetUrl]);
        }
    }
    
    if ($content === false) {
        sendHttp10Response(500);
        $errorHtml = "<html><head><title>Error</title></head><body>\n";
        $errorHtml .= renderNavigation($imageMode);
        $errorHtml .= "<h1>Error</h1>\n";
        $errorHtml .= "<p>Could not load page: " . htmlspecialchars($targetUrl) . "</p>\n";
        $errorHtml .= "</body></html>\n";
        setHttp10Headers(strlen($errorHtml));
        echo $errorHtml;
        exit;
    }
    
    // Check size
    if (strlen($content) > MAX_DOWNLOAD_SIZE) {
        logSecurityEvent('download_size_exceeded', ['size' => strlen($content), 'max' => MAX_DOWNLOAD_SIZE, 'url' => $targetUrl]);
        sendHttp10Response(413);
        $errorHtml = "<html><head><title>Error</title></head><body>\n";
        $errorHtml .= renderNavigation($imageMode);
        $errorHtml .= "<h1>Error</h1>\n";
        $errorHtml .= "<p>File too large (max " . (MAX_DOWNLOAD_SIZE / 1024 / 1024) . "MB)</p>\n";
        $errorHtml .= "</body></html>\n";
        setHttp10Headers(strlen($errorHtml));
        echo $errorHtml;
        exit;
    }
    
    // Stream als download
    sendHttp10Response(200);
    header('Content-Type: ' . $contentType);
    $filename = basename(parse_url($targetUrl, PHP_URL_PATH));
    if (empty($filename)) {
        $filename = 'download';
    }
    header('Content-Disposition: attachment; filename="' . $filename . '"');
    setHttp10Headers(strlen($content));
    echo $content;
    exit;
}

// Detecteer finale URL na redirects VOORDAT we content ophalen
// Dit is cruciaal voor correcte normalisatie van relatieve image URLs
$finalUrl = $targetUrl; // Default: gebruik originele URL

// Volg redirect chain handmatig om finale URL te bepalen
$currentUrl = $targetUrl;
$maxRedirects = defined('MAX_REDIRECT_DEPTH') ? MAX_REDIRECT_DEPTH : 10;
$redirectCount = 0;
$visitedUrls = [$targetUrl]; // Track bezochte URLs voor loop detectie

while (false && $redirectCount < $maxRedirects) {
    try {
        // Maak HEAD request ZONDER follow_location om redirects handmatig te volgen
        $timeout = defined('REQUEST_TIMEOUT') ? REQUEST_TIMEOUT : 30;
        $headContext = stream_context_create([
            'http' => [
                'method' => 'HEAD',
                'header' => "User-Agent: " . USER_AGENT . "\r\n",
                'follow_location' => 0, // NIET automatisch volgen
                'max_redirects' => 0,
                'timeout' => $timeout,
                'ignore_errors' => true
            ]
        ]);
        
        $headers = @get_headers($currentUrl, 1, $headContext);
        
        if ($headers && is_array($headers)) {
            // Check response status
            $statusCode = 0;
            if (isset($headers[0]) && preg_match('/HTTP\/[\d.]+ (\d+)/i', $headers[0], $matches)) {
                $statusCode = (int)$matches[1];
            }
            
            // Als status 200, dan zijn we op de finale URL
            if ($statusCode >= 200 && $statusCode < 300 && $statusCode !== 301 && $statusCode !== 302 && $statusCode !== 303 && $statusCode !== 307 && $statusCode !== 308) {
                $finalUrl = $currentUrl;
                break;
            }
            
            // Check voor Location header (redirect)
            $location = null;
            foreach ($headers as $key => $value) {
                if (strtolower($key) === 'location') {
                    $location = is_array($value) ? $value[0] : $value; // Neem eerste redirect
                    break;
                }
            }
            
            // Als er een Location header is, volg de redirect
            if ($location) {
                // Maak Location URL absoluut als nodig
                if (preg_match('/^https?:\/\//', $location)) {
                    $newUrl = $location;
                } else {
                    // Relatieve Location header - maak absoluut
                    $newUrl = normalizeImageUrl($location, $currentUrl);
                }
                
                // Check voor redirect loop
                if (checkRedirectLoop($visitedUrls, $newUrl)) {
                    logSecurityEvent('redirect_loop_detected', ['url' => $newUrl, 'visited' => $visitedUrls]);
                    error_log('Redirect loop detected for URL: ' . $newUrl);
                    $finalUrl = $currentUrl; // Gebruik laatste geldige URL
                    break;
                }
                
                // SSRF check voor nieuwe URL
                if (isInternalUrl($newUrl)) {
                    logSecurityEvent('ssrf_attempt_redirect', ['url' => $newUrl, 'original' => $targetUrl]);
                    sendHttp10Response(403);
                    $errorHtml = "<html><head><title>Forbidden</title></head><body>\n";
                    $errorHtml .= renderNavigation($imageMode);
                    $errorHtml .= "<h1>Forbidden</h1>\n";
                    $errorHtml .= "<p>Redirect leads to internal URL which is not allowed.</p>\n";
                    $errorHtml .= "</body></html>\n";
                    setHttp10Headers(strlen($errorHtml));
                    echo $errorHtml;
                    exit;
                }
                
                $currentUrl = $newUrl;
                $visitedUrls[] = $newUrl;
                $redirectCount++;
                continue; // Volg deze redirect
            }
        }
        
        // Geen redirect gevonden, gebruik huidige URL als finale
        $finalUrl = $currentUrl;
        break;
        
    } catch (Exception $e) {
        // Error bij redirect detectie, gebruik originele URL
        error_log('Redirect detection failed: ' . $e->getMessage());
        break;
    }
}

// Update targetUrl naar finale URL (na redirects)
// Dit is cruciaal voor correcte normalisatie van relatieve image URLs
$targetUrl = $finalUrl;

// Fetch HTML content (ondersteunt HTTPS) - gebruik finale URL
$getContext = createStreamContext('GET');
$html = $prefetchedContent;

// Als Content-Type nog niet bekend is, check het nu via response headers
$responseHeaders = [];
if (empty($contentType) && isset($http_response_header) && is_array($http_response_header)) {
    foreach ($http_response_header as $header) {
        if (preg_match('/^Content-Type:\s*(.+)$/i', $header, $matches)) {
            $contentType = strtolower(trim(explode(';', $matches[1])[0]));
        }
        $responseHeaders[] = $header;
    }
} elseif (isset($http_response_header) && is_array($http_response_header)) {
    $responseHeaders = $http_response_header;
        }

// Valideer Content-Length als content is opgehaald
if ($html !== false && !empty($html)) {
    if (!validateContentLength($html, $responseHeaders)) {
        logSecurityEvent('content_length_mismatch_proxy', ['url' => $targetUrl]);
        // Log maar blokkeer niet - content kan nog steeds geldig zijn
    }
}

if ($html === false) {
    sendHttp10Response(500);
    $errorHtml = "<html><head><title>Error</title></head><body>\n";
    $errorHtml .= renderNavigation($imageMode);
    $errorHtml .= "<h1>Error</h1>\n";
    $errorHtml .= "<p>Kon pagina niet laden: " . htmlspecialchars($targetUrl) . "</p>\n";
    $errorHtml .= "<p>Possible causes: page does not exist, server is offline, or access denied.</p>\n";
    $errorHtml .= "</body></html>\n";
    setHttp10Headers(strlen($errorHtml));
    echo $errorHtml;
    exit;
}

// Normaliseer encoding naar UTF-8 voordat we verder gaan
// Dit fix encoding problemen zoals "GefÃ¼hl" (UTF-8 verkeerd geïnterpreteerd als ISO-8859-1)
if (function_exists('mb_detect_encoding')) {
    $detected = mb_detect_encoding($html, ['UTF-8', 'ISO-8859-1', 'Windows-1252'], true);
    if ($detected && $detected !== 'UTF-8') {
        // Als het niet UTF-8 is, converteer naar UTF-8
        $html = mb_convert_encoding($html, 'UTF-8', $detected);
    } elseif (!$detected) {
        // Als encoding niet gedetecteerd kan worden, probeer UTF-8 te forceren
        // Check of het mogelijk verkeerd geïnterpreteerde UTF-8 is
        if (preg_match('/[\xC0-\xFF][\x80-\xBF]/', $html)) {
            // Mogelijk verkeerd geïnterpreteerde UTF-8 (zoals "GefÃ¼hl"), probeer te repareren
            $html = mb_convert_encoding($html, 'UTF-8', 'ISO-8859-1');
        }
    }
}

// Store originele HTML voor CSS parsing
$originalHtml = $html;

// Extract image URLs en dimensions uit originele HTML (voordat Readability)
$imageMap = []; // origUrl => normalizedUrl
$reverseImageMap = []; // normalizedUrl => origUrl (voor reverse lookup)
$imageDimensions = [];
$imagePathMap = []; // path/filename => normalizedUrl (voor matching op basis van pad)
preg_match_all('/<img[^>]+>/i', $originalHtml, $imgMatches);
foreach ($imgMatches[0] as $imgTag) {
    // Extract src URL
    if (preg_match('/src\s*=\s*["\']([^"\']+)["\']/i', $imgTag, $srcMatch)) {
        $imgUrl = $srcMatch[1];
        
        // BELANGRIJK: Als URL al absoluut is (met protocol en domein), gebruik die zoals die is
        // Dit behoudt externe domeinen
        if (preg_match('/^https?:\/\//', $imgUrl)) {
            // Absolute URL - gebruik zoals die is (behoud externe domeinen)
            $normalized = $imgUrl;
        } else {
            // Relatieve URL - normaliseer ten opzichte van targetUrl
            // MAAR: als de relatieve URL begint met //, is het protocol-relative
            if (preg_match('/^\/\//', $imgUrl)) {
                // Protocol-relative URL - voeg scheme toe van targetUrl
                $targetParts = parse_url($targetUrl);
                $scheme = isset($targetParts['scheme']) ? $targetParts['scheme'] : 'https';
                $normalized = $scheme . ':' . $imgUrl;
            } else {
                // Normale relatieve URL - normaliseer ten opzichte van targetUrl
                $normalized = normalizeImageUrl($imgUrl, $targetUrl);
            }
        }
        
        $imageMap[$imgUrl] = $normalized;
        $reverseImageMap[$normalized] = $imgUrl; // Reverse lookup
        
        // Maak ook een path map voor matching op basis van pad/filename
        $imgPath = parse_url($normalized, PHP_URL_PATH);
        if ($imgPath) {
            $imgFilename = basename($imgPath);
            $imgPathParts = explode('/', trim($imgPath, '/'));
            // Sla op: filename => normalizedUrl (gebruik array voor meerdere matches)
            if ($imgFilename) {
                if (!isset($imagePathMap[$imgFilename])) {
                    $imagePathMap[$imgFilename] = [];
                }
                $imagePathMap[$imgFilename][] = $normalized;
            }
            // Sla ook laatste 2 path delen op voor betere matching
            if (count($imgPathParts) >= 2) {
                $lastTwoParts = implode('/', array_slice($imgPathParts, -2));
                if (!isset($imagePathMap[$lastTwoParts])) {
                    $imagePathMap[$lastTwoParts] = [];
                }
                $imagePathMap[$lastTwoParts][] = $normalized;
            }
            // Sla ook volledige path op (zonder query string)
            $fullPath = trim($imgPath, '/');
            if ($fullPath) {
                if (!isset($imagePathMap[$fullPath])) {
                    $imagePathMap[$fullPath] = [];
                }
                $imagePathMap[$fullPath][] = $normalized;
            }
        }
        
        // Extract dimensions voor later gebruik
        $dimensions = extractImageDimensions($imgTag, $originalHtml);
        $imageDimensions[$normalized] = $dimensions;
    }
}

// Strip moderne tags (maar bewaar style tags tijdelijk voor CSS parsing)
$htmlForExtraction = stripModernTags($html);

// Parse met content extractor (configureerbaar via config.php)
try {
    $extractor = getContentExtractor();
    $result = $extractor->extract($htmlForExtraction, $targetUrl);
    
    if ($result === false || empty($result['content'])) {
        // Fallback: gebruik originele HTML
        $title = 'Page';
        $content = $htmlForExtraction;
    } else {
        $title = $result['title'] ?: 'Page';
        $content = $result['content'];
    }
    
    // Sanitize title: verwijder control characters en limiteer lengte
    $title = preg_replace('/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/', '', $title);
    $title = mb_substr(trim($title), 0, 200); // Max 200 karakters
    
    // Converteer umlauts en speciale karakters naar HTML entities voor HTML 2.0
    $title = htmlentities($title, ENT_QUOTES | ENT_SUBSTITUTE, 'ISO-8859-1', false);
    
    // Sanitize content: verwijder control characters (behalve whitespace)
    $content = preg_replace('/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/', '', $content);
    
    // Check of extractor images heeft behouden
    // Als extractor images heeft verwijderd, voeg ze opnieuw toe uit originalHtml
    $contentImageCount = preg_match_all('/<img[^>]*>/i', $content);
    $originalImageCount = count($imageMap);
    
    // Als extractor veel images heeft verwijderd, voeg ze opnieuw toe
    if ($contentImageCount < $originalImageCount * 0.5 && $originalImageCount > 0) {
        // Extractor heeft waarschijnlijk images verwijderd
        // Voeg belangrijke images opnieuw toe aan het einde van de content
        $addedImages = [];
        foreach ($imageMap as $origUrl => $normUrl) {
            if (!preg_match('/' . preg_quote($normUrl, '/') . '/i', $content)) {
                // Image niet gevonden in content, voeg toe
                $imgTag = '<img src="' . htmlspecialchars($normUrl) . '">';
                $addedImages[] = $imgTag;
            }
        }
        // Voeg images toe aan einde van content
        if (!empty($addedImages)) {
            $content .= '<p>' . implode(' ', $addedImages) . '</p>';
        }
    }
} catch (Exception $e) {
    // Catch alle exceptions
    error_log('Content extractor error: ' . $e->getMessage());
    $title = 'Page';
    $content = $htmlForExtraction;
    
    // Sanitize title en content
    $title = preg_replace('/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/', '', $title);
    $title = mb_substr(trim($title), 0, 200);
    $content = preg_replace('/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/', '', $content);
    
    // Converteer umlauts en speciale karakters naar HTML entities voor HTML 2.0
    $title = htmlentities($title, ENT_QUOTES | ENT_SUBSTITUTE, 'ISO-8859-1', false);
}

// Filter toegestane tags met DOMDocument
$allowedTags = '<a><ol><ul><li><br><p><small><font><b><strong><i><em><blockquote><h1><h2><h3><h4><h5><h6><img>';
$content = strip_tags($content, $allowedTags);

// Converteer moderne tags
$content = convertModernTags($content);

// Clean speciale karakters
$content = cleanSpecialCharacters($content);

// Converteer umlauts en speciale karakters naar HTML entities voor HTML 2.0
$content = convertToHtmlEntities($content);

// Vervang image URLs in content met originele URLs uit imageMap
// Dit voorkomt dat Readability-gewijzigde URLs verkeerd worden genormaliseerd
$content = preg_replace_callback(
    '/<img([^>]+src\s*=\s*["\'])([^"\']+)(["\'][^>]*)>/i',
    function($matches) use ($imagePathMap, $imageMap, $reverseImageMap) {
        $imgUrl = $matches[2];
        $replacementUrl = $imgUrl;
        
        // Eerst checken of deze exacte URL al in imageMap staat
        if (isset($imageMap[$imgUrl])) {
            $replacementUrl = $imageMap[$imgUrl];
        } elseif (isset($reverseImageMap[$imgUrl])) {
            // URL staat in reverse map, gebruik zoals die is
            $replacementUrl = $imgUrl;
        } else {
            // Probeer te matchen op basis van path/filename
            $imgPath = parse_url($imgUrl, PHP_URL_PATH) ?: $imgUrl;
            $imgFilename = basename($imgPath);
            $imgPathClean = trim($imgPath, '/');
            
            // Check volledige path match eerst (meest betrouwbaar)
            if ($imgPathClean && isset($imagePathMap[$imgPathClean]) && !empty($imagePathMap[$imgPathClean])) {
                $replacementUrl = $imagePathMap[$imgPathClean][0]; // Neem eerste match
            } elseif ($imgFilename && isset($imagePathMap[$imgFilename]) && !empty($imagePathMap[$imgFilename])) {
                // Check filename match
                $replacementUrl = $imagePathMap[$imgFilename][0]; // Neem eerste match
            } else {
                // Check path match (laatste 2 delen)
                $imgPathParts = explode('/', $imgPathClean);
                if (count($imgPathParts) >= 2) {
                    $lastTwoParts = implode('/', array_slice($imgPathParts, -2));
                    if (isset($imagePathMap[$lastTwoParts]) && !empty($imagePathMap[$lastTwoParts])) {
                        $replacementUrl = $imagePathMap[$lastTwoParts][0]; // Neem eerste match
                    }
                }
                
                // Als nog steeds niet gevonden, check alle imageMap entries
                if ($replacementUrl === $imgUrl) {
                    foreach ($imageMap as $origUrl => $normUrl) {
                        // Check of path/filename overeenkomt
                        $origPath = parse_url($origUrl, PHP_URL_PATH) ?: $origUrl;
                        $normPath = parse_url($normUrl, PHP_URL_PATH) ?: $normUrl;
                        
                        if (basename($origPath) === $imgFilename || basename($normPath) === $imgFilename) {
                            $replacementUrl = $normUrl;
                            break;
                        }
                    }
                }
            }
        }
        
        // Vervang src URL
        return '<img' . $matches[1] . $replacementUrl . $matches[3] . '>';
    },
    $content
);

// Verwerk images volgens mode - SIMPELE IMPLEMENTATIE
$imageCounter = 0;
$basePath = getBasePath();
$baseUrl = getBaseUrl();

// Bewaar content voor detectie van <a> tags (voordat we images vervangen)
$contentBeforeImageReplacement = $content;

// Vervang ALLE img tags in content met simpele logica
$content = preg_replace_callback(
    '/<img([^>]*)>/i',
    function($matches) use (&$imageCounter, $contentBeforeImageReplacement, $basePath, $baseUrl, $targetUrl, $originalHtml, $imageMode, $imageMap, $reverseImageMap, $imagePathMap) {
        $imgTag = $matches[0];
        $imgAttrs = $matches[1];
        $imageCounter++;
        
        // Extract src URL
        if (!preg_match('/src\s*=\s*["\']([^"\']+)["\']/i', $imgTag, $srcMatch)) {
            return $imgTag; // Geen src, return origineel
        }
        
        $imgUrl = $srcMatch[1];
        
        // Check eerst of deze URL al in imageMap staat (originele extractie)
        // Dit voorkomt dat Readability-gewijzigde URLs verkeerd worden genormaliseerd
        $normalizedUrl = null;
        if (isset($imageMap[$imgUrl])) {
            // URL staat in map, gebruik genormaliseerde versie
            $normalizedUrl = $imageMap[$imgUrl];
        } else {
            // URL niet in map, normaliseer nu
            $normalizedUrl = normalizeImageUrl($imgUrl, $targetUrl);
            
            // Check of de genormaliseerde URL al in reverseImageMap staat
            // Dit helpt als Readability de URL heeft aangepast
            if (isset($reverseImageMap[$normalizedUrl])) {
                // We hebben de originele URL gevonden, gebruik de genormaliseerde versie
                // (die is al correct)
            } else {
                // Check of de genormaliseerde URL al in reverseImageMap staat
                // Dit helpt als Readability de URL heeft aangepast
                if (isset($reverseImageMap[$normalizedUrl])) {
                    // We hebben de originele URL gevonden, gebruik de genormaliseerde versie
                    // (die is al correct)
                } else {
                    // Check op basis van path/filename in imagePathMap
                    $imgPath = parse_url($normalizedUrl, PHP_URL_PATH);
                    if ($imgPath) {
                        $imgFilename = basename($imgPath);
                        $imgPathParts = explode('/', trim($imgPath, '/'));
                        
                        // Check filename match
                        if ($imgFilename && isset($imagePathMap[$imgFilename])) {
                            $normalizedUrl = $imagePathMap[$imgFilename];
                        } elseif (count($imgPathParts) >= 2) {
                            // Check laatste 2 path delen
                            $lastTwoParts = implode('/', array_slice($imgPathParts, -2));
                            if (isset($imagePathMap[$lastTwoParts])) {
                                $normalizedUrl = $imagePathMap[$lastTwoParts];
                            }
                        }
                    }
                    
                    // Als nog steeds niet gevonden, check alle imageMap entries
                    if (!isset($reverseImageMap[$normalizedUrl])) {
                        foreach ($imageMap as $origUrl => $normUrl) {
                            // Check exacte match
                            if ($normUrl === $normalizedUrl || $normUrl === $imgUrl || $imgUrl === $origUrl) {
                                $normalizedUrl = $normUrl;
                                break;
                            }
                        }
                    }
                }
            }
        }
        
        // Check of image verborgen moet worden
        if (shouldHideImage($imgTag, $normalizedUrl, $originalHtml)) {
            return ''; // Verberg image
        }
        
        // Haal dimensions op uit huidige tag
        $dimensions = extractImageDimensions($imgTag, $originalHtml);
        
        // Bereken gelimiteerde dimensions met aspect ratio behoud
        $displayWidth = $dimensions['width'];
        $displayHeight = $dimensions['height'];
        
        // Als beide dimensions bekend zijn, behoud aspect ratio
        if ($displayWidth !== null && $displayHeight !== null && $displayWidth > 0 && $displayHeight > 0) {
            // Bereken aspect ratio
            $aspectRatio = $displayWidth / $displayHeight;
            
            // Limiteer tot max 300x300 met aspect ratio behoud
            if ($displayWidth > MAX_IMAGE_WIDTH || $displayHeight > MAX_IMAGE_HEIGHT) {
                // Bereken nieuwe dimensies met aspect ratio behoud
                $ratio = min(MAX_IMAGE_WIDTH / $displayWidth, MAX_IMAGE_HEIGHT / $displayHeight);
                $displayWidth = (int)($displayWidth * $ratio);
                $displayHeight = (int)($displayHeight * $ratio);
            }
        } else {
            // Als alleen één dimensie bekend is, limiteer die
            if ($displayWidth !== null && $displayWidth > MAX_IMAGE_WIDTH) {
                $displayWidth = MAX_IMAGE_WIDTH;
            }
            if ($displayHeight !== null && $displayHeight > MAX_IMAGE_HEIGHT) {
                $displayHeight = MAX_IMAGE_HEIGHT;
            }
        }
        
        $encodedUrl = urlencode($normalizedUrl);
        
        if ($imageMode === 'inline') {
            // Inline mode: ALTIJD via image_cruncher.php
            $compressedUrl = $baseUrl . '/image_cruncher.php?url=' . $encodedUrl;
            // Geef alleen width door (height volgt automatisch via aspect ratio)
            if ($dimensions['width'] !== null && $dimensions['width'] <= MAX_IMAGE_WIDTH) {
                $compressedUrl .= '&w=' . $dimensions['width'];
            }
            
            // Extract alt text (behoud alleen alt)
            $altText = '';
            if (preg_match('/alt\s*=\s*["\']([^"\']*)["\']/i', $imgTag, $altMatch)) {
                $altText = $altMatch[1];
            }
            
            // Bouw nieuwe, schone img tag met alleen src en alt (geen width/height)
            $newImgTag = '<img src="' . htmlspecialchars($compressedUrl) . '"';
            
            if (!empty($altText)) {
                $newImgTag .= ' alt="' . htmlspecialchars($altText) . '"';
            }
            
            $newImgTag .= '>';
            
            // Wrap in <p> tag zodat image altijd op eigen regel staat
            return '<p>' . $newImgTag . '</p>';
        } else {
            // Links mode: vervang met genummerde link
            // Check of image binnen een <a> tag staat om geneste links te voorkomen
            $isInsideAnchor = false;
            $anchorTag = '';
            $anchorHref = '';
            // Vind de positie van deze image tag in de originele content (voor replacement)
            $imgTagPos = strpos($contentBeforeImageReplacement, $imgTag);
            if ($imgTagPos !== false) {
                // Haal content voor deze image tag op
                $contentBefore = substr($contentBeforeImageReplacement, 0, $imgTagPos);
                // Tel open en gesloten <a> tags
                $openAnchors = preg_match_all('/<a\s+[^>]*>/i', $contentBefore, $anchorMatches, PREG_OFFSET_CAPTURE);
                $closeAnchors = preg_match_all('/<\/a>/i', $contentBefore, $closeMatches, PREG_OFFSET_CAPTURE);
                // Als er meer open dan gesloten <a> tags zijn, staan we binnen een <a> tag
                $isInsideAnchor = ($openAnchors > $closeAnchors);
                
                if ($isInsideAnchor && !empty($anchorMatches[0])) {
                    // Haal de laatste (meest recente) <a> tag op
                    $lastAnchor = end($anchorMatches[0]);
                    $anchorTag = $lastAnchor[0];
                    // Extract href uit anchor tag
                    if (preg_match('/href\s*=\s*["\']([^"\']+)["\']/i', $anchorTag, $hrefMatch)) {
                        $anchorHref = $hrefMatch[1];
                    }
                }
            }
            
            $imageViewerUrl = $baseUrl . '/proxy.php?url=' . urlencode($normalizedUrl) . '&img=' . $imageMode;
            $imageLink = '<a href="' . htmlspecialchars($imageViewerUrl) . '"><b>[Image ' . $imageCounter . ']</b></a>';
            
            if ($isInsideAnchor && !empty($anchorTag)) {
                // Image staat binnen een <a> tag: sluit de <a> tag, voeg image link toe, en heropen <a> tag
                // Dit zorgt ervoor dat beide links klikbaar zijn zonder geneste links
                // Behoud alle attributen van de originele <a> tag
                return '</a><br>' . $imageLink . '<br>' . $anchorTag;
            } else {
                // Image staat niet binnen een <a> tag: maak klikbare link
                return '<br>' . $imageLink;
            }
        }
    },
    $content
);

// Cleanup: verwijder geneste <p> tags (als image al in <p> tag stond)
$content = preg_replace('/<p>\s*<p>/i', '<p>', $content);
$content = preg_replace('/<\/p>\s*<\/p>/i', '</p>', $content);

// Update alle links om image mode parameter mee te nemen
$content = preg_replace_callback(
    '/<a\s+([^>]*href\s*=\s*["\'])([^"\']+)(["\'][^>]*)>/i',
    function($matches) use ($imageMode, $basePath, $baseUrl) {
        $href = $matches[2];
        
        // Als interne link (proxy.php), voeg image mode toe
        if (strpos($href, $basePath . '/proxy.php') === 0 || strpos($href, 'proxy.php') === 0 || strpos($href, $baseUrl . '/proxy.php') === 0) {
            $separator = strpos($href, '?') !== false ? '&' : '?';
            $href = $href . $separator . 'img=' . $imageMode;
        } elseif (!preg_match('/^https?:\/\//', $href) && !preg_match('/^mailto:/', $href)) {
            // Relatieve link, converteer naar proxy.php
            $targetBaseUrl = isset($_GET['url']) ? $_GET['url'] : '';
            if ($targetBaseUrl) {
                $normalizedHref = normalizeImageUrl($href, $targetBaseUrl);
                $href = $baseUrl . '/proxy.php?url=' . urlencode($normalizedHref) . '&img=' . $imageMode;
            }
        } elseif (preg_match('/^https?:\/\//', $href)) {
            // Externe link, route door proxy.php
            $href = $baseUrl . '/proxy.php?url=' . urlencode($href) . '&img=' . $imageMode;
        }
        
        return '<a ' . $matches[1] . $href . $matches[3] . '>';
    },
    $content
);

// Verplaats menu's naar het einde van de content
// Detecteer menu's (veel links in een lijst, of elementen met menu/nav classes)
$menus = [];
$menuPlaceholders = [];

// Functie om geneste <ul> tags te matchen (recursief)
function matchNestedUl($html, $startPos = 0) {
    $pos = strpos($html, '<ul', $startPos);
    if ($pos === false) {
        return null;
    }
    
    // Vind de opening tag einde
    $tagEnd = strpos($html, '>', $pos);
    if ($tagEnd === false) {
        return null;
    }
    
    // Zoek naar de bijbehorende closing tag (rekening houdend met geneste <ul>)
    $depth = 1;
    $searchPos = $tagEnd + 1;
    $endPos = null;
    
    while ($depth > 0 && $searchPos < strlen($html)) {
        $nextOpen = strpos($html, '<ul', $searchPos);
        $nextClose = strpos($html, '</ul>', $searchPos);
        
        if ($nextClose === false) {
            break; // Geen closing tag gevonden
        }
        
        if ($nextOpen !== false && $nextOpen < $nextClose) {
            // Er is een geneste <ul> gevonden
            $depth++;
            $searchPos = strpos($html, '>', $nextOpen) + 1;
        } else {
            // Closing tag gevonden
            $depth--;
            if ($depth === 0) {
                $endPos = $nextClose + 5; // +5 voor '</ul>'
                break;
            }
            $searchPos = $nextClose + 5;
        }
    }
    
    if ($endPos !== null) {
        return [
            'start' => $pos,
            'end' => $endPos,
            'content' => substr($html, $pos, $endPos - $pos)
        ];
    }
    
    return null;
}

// Extract alle <ul> tags en check of ze menu's zijn
$offset = 0;
while (($match = matchNestedUl($content, $offset)) !== null) {
    $ulContent = $match['content'];
    $linkCount = preg_match_all('/<a[^>]*>/i', $ulContent);
    
    // Check of het een menu is:
    // 1. Meer dan 5 links (waarschijnlijk navigatie)
    // 2. Heeft menu/nav classes of ids
    // 3. Heeft sub-menu classes
    $isMenu = false;
    
    if ($linkCount > 5) {
        $isMenu = true;
    } elseif (preg_match('/(?:class|id)=["\'][^"\']*(?:menu|nav|navigation|sub-menu)[^"\']*["\']/i', $ulContent)) {
        $isMenu = true;
    } elseif (preg_match('/menu-item|menu-item-type/i', $ulContent)) {
        $isMenu = true;
    }
    
    if ($isMenu) {
        $placeholder = '<!--MENU_' . count($menus) . '-->';
        $menus[] = $ulContent;
        $menuPlaceholders[] = $placeholder;
        // Vervang menu met placeholder
        $content = substr_replace($content, $placeholder, $match['start'], $match['end'] - $match['start']);
        $offset = $match['start'] + strlen($placeholder);
    } else {
        $offset = $match['end'];
    }
}

// Voeg menu's toe aan het einde van de content
if (!empty($menus)) {
    $content .= '<hr><h2>Menu</h2>';
    foreach ($menus as $menu) {
        $content .= $menu . '<br>';
    }
}

// Extract kleuren uit originele HTML
$colors = extractColors($originalHtml);
$bodyAttrs = '';

// Als tekstkleur licht is, forceer zwarte achtergrond
if (!empty($colors['text']) && isLightColor($colors['text'])) {
    $bodyAttrs .= ' bgcolor="#000000"';
    // Behoud originele tekstkleur
    $bodyAttrs .= ' text="' . htmlspecialchars($colors['text']) . '"';
} else {
    // Gebruik originele achtergrondkleur als beschikbaar
    if (!empty($colors['bgcolor'])) {
        $bodyAttrs .= ' bgcolor="' . htmlspecialchars($colors['bgcolor']) . '"';
    }
    
    // Gebruik originele tekstkleur als beschikbaar
    if (!empty($colors['text'])) {
        $bodyAttrs .= ' text="' . htmlspecialchars($colors['text']) . '"';
    }
}

// Gebruik originele link kleur als beschikbaar
if (!empty($colors['link'])) {
    $bodyAttrs .= ' link="' . htmlspecialchars($colors['link']) . '"';
}

// Split only after extraction, cleanup, link and image rewriting. The paginator
// budgets the actual ISO-8859-1 output including both navigation bars.
try {
    $htmlOutput = $pagePaginator->first($content, $title, renderNavigation($imageMode), $bodyAttrs, $baseUrl);
    sendHttp10Response(200);
} catch (RuntimeException $error) {
    sendHttp10Response(503, 'Service Unavailable');
    $htmlOutput = '<html><head><title>RetroWEB</title></head><body><h1>Page temporarily unavailable</h1>'
        . '<p>The page could not be divided for this browser. Please try again later.</p></body></html>';
    error_log('RetroWEB pagination: ' . $error->getMessage());
}

// Output (geen cache)
header('Content-Type: text/html; charset=iso-8859-1');
setHttp10Headers(strlen($htmlOutput));
echo $htmlOutput;
