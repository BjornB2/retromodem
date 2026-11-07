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
setHtmlNoCacheHeaders();

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
$activeSettings = getUserSettings();
rememberUserSettings($activeSettings);
registerAggregateProcessing('page', $activeSettings['resolved_profile']);
$pageSize = $activeSettings['page_size'];
$pageImages = $activeSettings['page_images'];
$pageLanguage = retromodemNavigationLanguage();
$pagePaginator = new RetroWebPagePaginator(CACHE_DIR . '/pages', $pageSize, $pageImages,
    3600, 128, 67108864, $pageLanguage, RENDER_VERSION);
if (isset($_GET['document'])) {
    $document = is_string($_GET['document']) ? $_GET['document'] : '';
    $part = isset($_GET['part']) ? (is_string($_GET['part']) ? $_GET['part'] : '') : '1';
    $mode = isset($_GET['img']) ? (is_string($_GET['img']) ? $_GET['img'] : '') : null;
    $block = isset($_GET['block']) ? (is_string($_GET['block']) ? $_GET['block'] : '') : null;
    $selectedPage = $pagePaginator->read($document, $part, $mode, $block);
    $selectedPage['html'] = prepareLegacyBrowserHtml($selectedPage['html'], $activeSettings);
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

$retroSessionId = isset($_COOKIE['retroweb_session']) && is_string($_COOKIE['retroweb_session'])
    && preg_match('/^[a-f0-9]{32}$/', $_COOKIE['retroweb_session']) ? $_COOKIE['retroweb_session'] : bin2hex(random_bytes(16));
if (!isset($_COOKIE['retroweb_session']) || $_COOKIE['retroweb_session'] !== $retroSessionId) {
    setcookie('retroweb_session', $retroSessionId, ['expires'=>time()+86400, 'path'=>getBasePath()==='/'?'/':getBasePath().'/',
        'secure'=>false, 'httponly'=>true, 'samesite'=>'Lax']);
}
$upstreamCookies = new \RetroWEB\UpstreamCookieJar(CACHE_DIR . '/cookies', $retroSessionId);

// Content extractor wordt via config.php geladen

// Haal URL parameter op (met fallback voor HTTP/1.0 browsers)
$targetUrl = '';
if (isset($_GET['url'])) {
    $targetUrl = trim($_GET['url']);
} elseif (isset($_POST['url']) && is_string($_POST['url'])) {
    $targetUrl = trim($_POST['url']);
} elseif (!empty($_SERVER['QUERY_STRING'])) {
    // Fallback: parse QUERY_STRING handmatig als $_GET niet werkt
    parse_str($_SERVER['QUERY_STRING'], $params);
    if (isset($params['url'])) {
        $targetUrl = trim($params['url']);
    }
}

$submittedFields = \RetroWEB\LegacyFormConverter::submittedFields(
    ($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST' ? $_POST : $_GET
);
$upstreamMethod = ($_SERVER['REQUEST_METHOD'] ?? 'GET') === 'POST' && $submittedFields ? 'POST' : 'GET';

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

if ($upstreamMethod === 'GET' && $submittedFields) {
    $targetUrl .= (str_contains($targetUrl, '?') ? '&' : '?') . \RetroWEB\LegacyFormConverter::encodeFields($submittedFields);
}

// Cache uitgeschakeld - altijd live content

// Check Content-Type via HEAD request (met fallback)
$contentType = '';
try {
    $cookieHeader = $upstreamCookies->headerFor($targetUrl);
    $headResponse = \RetroWEB\SecureHttpClient::request($targetUrl, 'HEAD', null,
        $cookieHeader !== null ? ['Cookie'=>$cookieHeader] : [], 1024, MAX_REDIRECT_DEPTH);
    $headContentType = \RetroWEB\SecureHttpClient::header($headResponse['headers'], 'Content-Type');
    if ($headContentType !== null) $contentType = strtolower(trim(explode(';', $headContentType)[0]));
} catch (Throwable $e) {
    // Ignore errors bij HEAD request, we proberen het later met GET
    error_log('HEAD request failed: ' . $e->getMessage());
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
if ($upstreamMethod === 'GET' && !empty($contentType) && $contentType !== 'text/html' && $contentType !== 'text/plain') {
    $cookieHeader = $upstreamCookies->headerFor($targetUrl);
    try {
        $downloadResponse = \RetroWEB\SecureHttpClient::request($targetUrl, 'GET', null,
            $cookieHeader !== null ? ['Cookie'=>$cookieHeader] : [], MAX_DOWNLOAD_SIZE, MAX_REDIRECT_DEPTH);
        $content = $downloadResponse['data'];
        $downloadHeaders = $downloadResponse['headers'];
    } catch (Throwable $error) {
        $content = false; $downloadHeaders = [];
    }

    // Validate Content-Length for download content
    $upstreamCookies->capture($downloadHeaders, $targetUrl);
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

if ($upstreamMethod === 'GET') while ($redirectCount < $maxRedirects) {
    try {
        // Maak HEAD request ZONDER follow_location om redirects handmatig te volgen
        $timeout = defined('REQUEST_TIMEOUT') ? REQUEST_TIMEOUT : 30;
        $redirectCookie = $upstreamCookies->headerFor($currentUrl);
        $headContext = stream_context_create([
            'http' => [
                'method' => 'HEAD',
                'header' => "User-Agent: " . USER_AGENT . "\r\n" . ($redirectCookie !== null ? 'Cookie: ' . $redirectCookie . "\r\n" : ''),
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

// Fetch HTML content (ondersteunt HTTPS) - gebruik finale URL.
try {
    $upstreamResponse = \RetroWEB\UpstreamFetcher::fetch($targetUrl, $upstreamMethod, $submittedFields, $upstreamCookies);
    $html = $upstreamResponse['data'];
    $lastResponseHeaders = $upstreamResponse['headers'];
    $targetUrl = $upstreamResponse['url'];
} catch (RuntimeException $fetchError) {
    $html = false;
    $lastResponseHeaders = [];
}

// Als Content-Type nog niet bekend is, check het nu via response headers
$responseHeaders = [];
if (empty($contentType) && $lastResponseHeaders) {
    foreach ($lastResponseHeaders as $header) {
        if (preg_match('/^Content-Type:\s*(.+)$/i', $header, $matches)) {
            $contentType = strtolower(trim(explode(';', $matches[1])[0]));
        }
        $responseHeaders[] = $header;
    }
} elseif ($lastResponseHeaders) {
    $responseHeaders = $lastResponseHeaders;
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
    $content = \RetroWEB\LegacyHtmlSanitizer::removeHiddenContent($content);
    
    // Sanitize title: verwijder control characters en limiteer lengte
    $title = preg_replace('/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/', '', $title);
    $title = mb_substr(trim($title), 0, 200); // Max 200 karakters
    
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
    
}

// Apply explicit CSS visual ordering before classes and styles are removed.
$content = \RetroWEB\LegacyHtmlConverter::applyVisualOrder($content, $originalHtml);

// Rewrite ordinary forms through RetroWEB before filtering attributes/tags.
$content = \RetroWEB\LegacyFormConverter::rewrite($content, $targetUrl, $baseUrl . '/proxy.php', $activeSettings);

// Convert tables according to the selected browser capability before filtering.
$tableMode = \RetroWEB\LegacyHtmlConverter::tableMode($activeSettings['tables'], $activeSettings['html']);
$content = \RetroWEB\LegacyHtmlConverter::convertTables($content, $tableMode, $activeSettings['html']);
$layoutMode = \RetroWEB\LegacyHtmlConverter::layoutMode($activeSettings['layout'], $activeSettings['html']);
$content = \RetroWEB\LegacyHtmlConverter::convertLayout($content, $layoutMode, $activeSettings['html'], $originalHtml);
$content = \RetroWEB\LegacyHtmlConverter::preserveBlockSpacing($content);
$content = \RetroWEB\LegacyHtmlConverter::relocateMenus($content);
$content = \RetroWEB\LegacyHtmlSanitizer::sanitiseAttributes($content);

// Render the final allowlisted legacy DOM without regex-based tag stripping.
$allowTables = $tableMode !== 'linearise' || $layoutMode === 'table';
$content = \RetroWEB\LegacyDomRenderer::render($content, $allowTables);
$content = \RetroWEB\LegacyHtmlConverter::normaliseBlockSpacing($content);

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
            $href = buildRetroWebUrl('proxy.php', \RetroWEB\UserSettings::query(getUserSettings(), ['url'=>normalizeImageUrl($href, $targetUrl)]));
        } else {
            parse_str(parse_url($href, PHP_URL_QUERY) ?? '', $parameters);
            unset($parameters['img']);
            $href = $baseUrl . '/proxy.php?' . http_build_query($parameters);
        }
        return '<a ' . $matches[1] . htmlspecialchars($href, ENT_QUOTES, 'ISO-8859-1', false) . $matches[3] . '>';
    },
    $content
);
$content = \RetroWEB\LegacyHtmlSanitizer::sanitiseAttributes($content);

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

// Paginate only the final cleaned and rewritten content.
try {
    $reloadUrl = buildRetroWebUrl('proxy.php', \RetroWEB\UserSettings::query($activeSettings, ['url'=>$targetUrl]));
    $htmlOutput = $pagePaginator->first($content, $title, renderNavigation($imageMode, $reloadUrl), $bodyAttrs, $baseUrl, $imageMode, $reloadUrl);
    sendHttp10Response(200);
} catch (RuntimeException $error) {
    sendHttp10Response(503, 'Service Unavailable');
    $htmlOutput = '<html><head><title>RetroWEB</title></head><body><h1>Page temporarily unavailable</h1>'
        . '<p>The page could not be divided for this browser. Please try again later.</p></body></html>';
    error_log('RetroWEB pagination: ' . $error->getMessage());
}

// Output (geen cache)
$htmlOutput = prepareLegacyBrowserHtml($htmlOutput, $activeSettings);
header('Content-Type: text/html; charset=iso-8859-1');
setHttp10Headers(strlen($htmlOutput));
echo $htmlOutput;
