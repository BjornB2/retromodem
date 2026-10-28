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
$pageSize = is_string($pageSize) && in_array($pageSize, ['0', '12000', '18000', '25000', '50000', '75000', '100000', '125000', '150000', '175000', '200000', '250000', '500000', '750000', '1000000', '1250000', '1500000', '1750000', '2000000'], true) ? (int)$pageSize : 18000;
$pageImages = is_string($pageImages) && preg_match('/^(?:[0-9]|10)$/D', $pageImages) ? (int)$pageImages : 5;
$pageLanguage = retromodemNavigationLanguage();
$pagePaginator = new RetroWebPagePaginator(CACHE_DIR . '/pages', $pageSize, $pageImages,
    3600, 128, 67108864, $pageLanguage);
// Snapshot navigation is local and must not fetch the original site again.
// Handle it before requiring an origin URL or loading the content extractor.
if (isset($_GET['document'])) {
    $document = is_string($_GET['document']) ? $_GET['document'] : '';
    $part = isset($_GET['part']) ? (is_string($_GET['part']) ? $_GET['part'] : '') : '1';
    $mode = isset($_GET['img']) ? (is_string($_GET['img']) ? $_GET['img'] : '') : null;
    $block = isset($_GET['block']) ? (is_string($_GET['block']) ? $_GET['block'] : '') : null;
    $selectedPage = $pagePaginator->read($document, $part, $mode, $block);
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
$upstream = fetchModemUpstream($targetUrl, ($_GET['http_fallback'] ?? '') === '1');
$targetUrl = $upstream['url'];
$contentType = $upstream['type'];
$prefetchedContent = $upstream['body'];
$upstreamProblem = modemUpstreamProblem($upstream);
if ($upstreamProblem !== null) {
    $problemTitle = modemText('Website niet beschikbaar', 'Website unavailable');
    $retrySeconds = (int)($upstream['retry_seconds'] ?? 15);
    $page = '<html><head><title>' . $problemTitle . '</title><meta name="retromodem-source-error" content="1">'
        . '<meta name="retromodem-retry-seconds" content="' . $retrySeconds . '"></head><body><h1>' . $problemTitle . '</h1><p>'
        . htmlspecialchars($upstreamProblem) . '</p><p>Webadres: ' . htmlspecialchars($targetUrl)
        . '</p>' . ($upstream['status'] === 429 ? '<p>' . modemText('Wacht ongeveer ', 'Wait approximately ') . $retrySeconds . modemText(' seconden voor een nieuwe poging.', ' seconds before trying again.') . '</p>' : '') . '</body></html>';
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

// Preserve original image hints without reintroducing excluded site images.
$imageMap = [];
$imageDimensions = [];
preg_match_all('/<img[^>]+>/i', $originalHtml, $imgMatches);
foreach ($imgMatches[0] as $imgTag) {
    if (!preg_match('/\bsrc\s*=\s*["\']([^"\']+)["\']/i', $imgTag, $srcMatch)) continue;
    $imgUrl = html_entity_decode($srcMatch[1], ENT_QUOTES, 'UTF-8');
    $normalized = normalizeImageUrl($imgUrl, $targetUrl);
    $imageMap[$imgUrl] = $normalized;
    $dimensions = extractImageDimensions($imgTag, $originalHtml);
    if (preg_match('/\balt\s*=\s*["\']([^"\']*)["\']/i', $imgTag, $originalAlt)) {
        $dimensions['alt'] = $originalAlt[1];
    }
    $imageDimensions[$normalized] = isset($imageDimensions[$normalized])
        ? mergeImageHints($imageDimensions[$normalized], $dimensions) : $dimensions;
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
    
    // Respect extraction: do not append every removed site image to the article.
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

// Keep extracted images in place and retain dimension/alt/link metadata.
// Always produce canonical inline HTML; PagePaginator derives mode variants.
$basePath = getBasePath();
$baseUrl = getBaseUrl();
$content = renderCanonicalImages($content, $baseUrl, $targetUrl, $originalHtml, $imageMap, $imageDimensions);

// Canonical links do not bake in an image mode; per-document variants share
// one content snapshot. Opening another origin uses its ordinary defaults.
$content = preg_replace_callback(
    '/<a\s+([^>]*href\s*=\s*["\'])([^"\']+)(["\'][^>]*)>/i',
    function($matches) use ($baseUrl, $targetUrl) {
        $href = html_entity_decode($matches[2], ENT_QUOTES, 'UTF-8');
        if ($href === '' || $href[0] === '#' || preg_match('/^(?:mailto|tel):/i', $href)) return $matches[0];
        if (strpos($href, $baseUrl . '/proxy.php?') !== 0) {
            $href = $baseUrl . '/proxy.php?' . http_build_query(['url' => normalizeImageUrl($href, $targetUrl)]);
        } else {
            parse_str(parse_url($href, PHP_URL_QUERY) ?? '', $parameters);
            unset($parameters['img']);
            $href = $baseUrl . '/proxy.php?' . http_build_query($parameters);
        }
        return '<a ' . $matches[1] . htmlspecialchars($href, ENT_QUOTES, 'ISO-8859-1', false) . $matches[3] . '>';
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
if (($upstream['transport_note'] ?? '') === 'http-fallback') {
    $content = '<p><b>' . modemText('Deze oude website werkt alleen via onversleuteld HTTP.', 'This legacy website only works over unencrypted HTTP.') . '</b></p>' . $content;
}
if (($upstream['transport_note'] ?? '') === 'original-wikipedia') {
    $content = '<p><b>' . modemText('Wikiwand blokkeert de proxy. Hieronder staat het oorspronkelijke Wikipedia-artikel.', 'Wikiwand blocks the proxy. The original Wikipedia article is shown below.') . '</b></p>' . $content;
}
try {
    $htmlOutput = $pagePaginator->first($content, $title, renderNavigation($imageMode), $bodyAttrs, $baseUrl, $imageMode);
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
