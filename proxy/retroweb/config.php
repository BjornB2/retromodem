<?php
/**
 * RetroWEB - Configuratie
 */

// VROEGE REQUEST NORMALISATIE (VOOR ALLES ANDERS)
// Dit is cruciaal voor HTTP/1.0 browsers zoals MacWeb 2.0 die geen Host header sturen
// De webserver kan een 400 error geven VOORDAT PHP draait, dus normaliseer zo vroeg mogelijk
if (empty($_SERVER['HTTP_HOST']) && !empty($_SERVER['SERVER_NAME'])) {
    $_SERVER['HTTP_HOST'] = $_SERVER['SERVER_NAME'];
    if (!empty($_SERVER['SERVER_PORT']) && $_SERVER['SERVER_PORT'] != 80 && $_SERVER['SERVER_PORT'] != 443) {
        $_SERVER['HTTP_HOST'] .= ':' . $_SERVER['SERVER_PORT'];
    }
}

// Zorg dat REQUEST_URI beschikbaar is (fallback voor oude browsers)
if (empty($_SERVER['REQUEST_URI']) && !empty($_SERVER['SCRIPT_NAME'])) {
    $_SERVER['REQUEST_URI'] = $_SERVER['SCRIPT_NAME'];
    if (!empty($_SERVER['QUERY_STRING'])) {
        $_SERVER['REQUEST_URI'] .= '?' . $_SERVER['QUERY_STRING'];
    }
}

// Bereken base path dynamisch voor subfolder installaties
if (isset($_SERVER['SCRIPT_NAME']) && !empty($_SERVER['SCRIPT_NAME'])) {
    define('BASE_PATH', rtrim(dirname($_SERVER['SCRIPT_NAME']), '/') ?: '/');
} else {
    // Fallback als SCRIPT_NAME niet beschikbaar is
    define('BASE_PATH', '/');
}

// Cache configuratie
define('CACHE_DIR', __DIR__ . '/cache');
define('CACHE_TTL', 3600); // 1 uur voor succesvolle requests
define('CACHE_TTL_FAILED', 300); // 5 minuten voor failed requests
define('CACHE_VERSION', '1.4'); // Increment bij parsing logica wijzigingen

// Max download size voor non-HTML content (8MB)
define('MAX_DOWNLOAD_SIZE', 8 * 1024 * 1024);

// Image compression settings
// Reload only numeric image limits from the local config for every request.
// Never source/evaluate the file or expose other settings to the response.
function retromodemImageDimension(string $key, string $legacy, int $fallback): int {
    $path = getenv('RETROMODEM_CONFIG_FILE') ?: '/etc/retromodem/retromodem.env';
    $local = [];
    foreach (@file($path, FILE_IGNORE_NEW_LINES) ?: [] as $line) {
        if (preg_match('/^(RETROMODEM_(?:PROXY|68KPROXY)_IMAGE_(?:WIDTH|HEIGHT))=(.*)$/D', $line, $match)) {
            $value = trim($match[2], " \t\r\n\"'");
            if (ctype_digit($value) && (int)$value >= 16 && (int)$value <= 4096) {
                $local[$match[1]] = (int)$value;
            }
        }
    }
    foreach ([$local[$key] ?? null, $local[$legacy] ?? null, getenv($key), getenv($legacy)] as $value) {
        if (is_numeric($value) && (int)$value >= 16 && (int)$value <= 4096) return (int)$value;
    }
    return $fallback;
}
define('MAX_IMAGE_WIDTH', retromodemImageDimension('RETROMODEM_PROXY_IMAGE_WIDTH', 'RETROMODEM_68KPROXY_IMAGE_WIDTH', 200));
define('MAX_IMAGE_HEIGHT', retromodemImageDimension('RETROMODEM_PROXY_IMAGE_HEIGHT', 'RETROMODEM_68KPROXY_IMAGE_HEIGHT', 150));
define('MIN_IMAGE_SIZE', 32); // Verberg images kleiner dan 32x32
define('JPG_QUALITY', 70); // JPG compressie kwaliteit (0-100)

// GIF color palette settings
define('GIF_PALETTE_COLORS', 128); // Aantal kleuren in GIF palette (max 256, aanbevolen 64-128 voor oude browsers)
define('GIF_USE_DITHERING', true); // Gebruik dithering voor betere kleurovergangen

// User-Agent voor externe requests
define('USER_AGENT', getenv('RETROMODEM_PROXY_USER_AGENT') ?: 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36');

// Content extractor configuratie
// Opties: 'readability', 'custom', 'hybrid'
// - 'readability': Gebruik alleen fivefilters/readability.php
// - 'custom': Gebruik alleen CustomDOMExtractor (behoudt meer content)
// - 'hybrid': Probeer eerst Readability, fallback naar CustomDOMExtractor
define('CONTENT_EXTRACTOR', 'hybrid');

// Application environment
// Opties: 'production' of 'development'
// - 'production': Geen error display, alleen logging
// - 'development': Error display aan voor debugging
define('APP_ENV', 'production');

// Rate limiting configuratie
define('RATE_LIMIT_ENABLED', false);
define('RATE_LIMIT_REQUESTS', 200); // Aantal requests per window
define('RATE_LIMIT_WINDOW', 60); // Tijdvenster in seconden

// Resource limits
define('MAX_URL_LENGTH', 2048); // Maximum URL lengte in karakters
define('MAX_IMAGE_PROCESSING_SIZE', 10 * 1024 * 1024); // 10MB max voor image processing
define('IMAGE_PROCESSING_TIMEOUT', 30); // Timeout in seconden voor image processing

// Extra security limits
define('MAX_SEARCH_QUERY_LENGTH', 500); // Maximum search query lengte in karakters
define('MAX_REDIRECT_DEPTH', 10); // Maximum redirect depth
define('MAX_REQUEST_SIZE', 1024 * 1024); // 1MB max request size
define('REQUEST_TIMEOUT', 30); // Timeout in seconden voor externe requests

// Visitor tracking configuratie
define('VISITOR_TRACKING_ENABLED', false);
define('VISITOR_TRACKING_WINDOW', 3600); // 1 uur in seconden (configureerbaar, bijv. 21600 voor 6 uur)
define('STATS_CACHE_TTL', 5); // Cache stats voor 5 seconden om database queries te verminderen

// Zorg dat cache directory bestaat
if (!file_exists(CACHE_DIR)) {
    @mkdir(CACHE_DIR, 0755, true);
}

/**
 * Helper functies
 */

/**
 * Retourneert base path voor subfolder installaties
 */
function getBasePath() {
    return BASE_PATH;
}

/**
 * Retourneert volledige base URL met protocol en host
 * Voor oude browsers zoals MacWeb 2.0 die absolute URLs nodig hebben
 * @return string Volledige base URL (bijv. http://retroweb.heirman.nl)
 */
function getBaseUrl() {
    // Private core endpoint; the forward-proxy adapter removes this URL again.
    $host = '127.0.0.1:8090';
    
    // Detecteer protocol (HTTP vs HTTPS)
    $scheme = 'http';
    if (isset($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') {
        $scheme = 'https';
    } elseif (isset($_SERVER['SERVER_PORT']) && $_SERVER['SERVER_PORT'] == 443) {
        $scheme = 'https';
    }
    
    // Voeg base path toe voor subfolder installaties
    $basePath = getBasePath();
    // Als basePath alleen '/' is, gebruik geen trailing slash (voorkom dubbele //)
    if ($basePath === '/') {
        $basePath = '';
    }
    
    return $scheme . '://' . $host . $basePath;
}

/**
 * Check of URL naar interne/private netwerk verwijst (SSRF bescherming)
 * @param string $url URL om te checken
 * @return bool True als URL intern/private is (moet geblokkeerd worden)
 */
function isInternalUrl($url) {
    $parsed = parse_url($url);
    if (!$parsed || !isset($parsed['host'])) {
        return true; // Geen host = verdacht
    }
    
    $host = strtolower($parsed['host']);
    
    // Block localhost en variants
    $blockedHosts = [
        'localhost',
        '127.0.0.1',
        '0.0.0.0',
        '::1',
        '[::1]'
    ];
    
    // Check localhost variants
    foreach ($blockedHosts as $blocked) {
        if ($host === $blocked || strpos($host, $blocked . '.') === 0) {
            return true;
        }
    }
    
    // Resolve hostname naar IP
    $ip = @gethostbyname($host);
    if ($ip !== $host && $ip !== false) {
        // Check if IP is in private/reserved ranges
        if (!filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_NO_PRIV_RANGE | FILTER_FLAG_NO_RES_RANGE)) {
            return true; // Private/reserved IP
        }
        
        // Check voor localhost IPs
        if (in_array($ip, ['127.0.0.1', '::1', '0.0.0.0'])) {
            return true;
        }
    }
    
    // Block gevaarlijke protocols
    if (isset($parsed['scheme'])) {
        $scheme = strtolower($parsed['scheme']);
        if (in_array($scheme, ['file', 'gopher', 'dict'])) {
            return true;
        }
    }
    
    // Block AWS metadata service
    if (strpos($host, '169.254.169.254') !== false || $ip === '169.254.169.254') {
        return true;
    }
    
    // Check voor private IP ranges in hostname
    if (preg_match('/^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)/', $ip)) {
        return true;
    }
    
    return false;
}

/**
 * Normaliseer HTTP request voor compatibiliteit met HTTP/1.0 browsers
 * Zorgt voor fallback Host header en verbeterde GET parameter parsing
 */
function normalizeRequest() {
    // Zorg dat Host header beschikbaar is (fallback voor HTTP/1.0 browsers zonder Host header)
    if (empty($_SERVER['HTTP_HOST']) && !empty($_SERVER['SERVER_NAME'])) {
        $_SERVER['HTTP_HOST'] = $_SERVER['SERVER_NAME'];
        if (!empty($_SERVER['SERVER_PORT']) && $_SERVER['SERVER_PORT'] != 80 && $_SERVER['SERVER_PORT'] != 443) {
            $_SERVER['HTTP_HOST'] .= ':' . $_SERVER['SERVER_PORT'];
        }
    }
    
    // Parse QUERY_STRING handmatig als $_GET leeg is (voor oude browsers met parsing problemen)
    if (empty($_GET) && !empty($_SERVER['QUERY_STRING'])) {
        parse_str($_SERVER['QUERY_STRING'], $parsedGet);
        if (!empty($parsedGet)) {
            $_GET = array_merge($_GET, $parsedGet);
        }
    }
    
    // Zorg dat REQUEST_URI beschikbaar is als fallback
    if (empty($_SERVER['REQUEST_URI']) && !empty($_SERVER['SCRIPT_NAME'])) {
        $_SERVER['REQUEST_URI'] = $_SERVER['SCRIPT_NAME'];
        if (!empty($_SERVER['QUERY_STRING'])) {
            $_SERVER['REQUEST_URI'] .= '?' . $_SERVER['QUERY_STRING'];
        }
    }
}

/**
 * Initialiseer error handling op basis van APP_ENV
 */
function initErrorHandling() {
    // Normaliseer request eerst (voor HTTP/1.0 compatibiliteit)
    normalizeRequest();
    
    $isProduction = (defined('APP_ENV') && APP_ENV === 'production');
    
    if ($isProduction) {
        error_reporting(0);
        ini_set('display_errors', 0);
    } else {
        error_reporting(E_ALL);
        ini_set('display_errors', 1);
    }
    
    // Altijd errors loggen
    ini_set('log_errors', 1);
    ini_set('error_log', __DIR__ . '/error.log');
    
    // Set error handler
    set_error_handler(function($errno, $errstr, $errfile, $errline) {
        $errorMsg = "PHP Error [$errno]: $errstr in $errfile on line $errline\n";
        error_log($errorMsg, 3, __DIR__ . '/error.log');
        return false; // Laat PHP de error ook normaal afhandelen
    });
    
    // Set exception handler
    set_exception_handler(function($exception) {
        $errorMsg = "PHP Exception: " . $exception->getMessage() . "\n";
        $errorMsg .= "File: " . $exception->getFile() . "\n";
        $errorMsg .= "Line: " . $exception->getLine() . "\n";
        $errorMsg .= $exception->getTraceAsString() . "\n";
        error_log($errorMsg, 3, __DIR__ . '/error.log');
        if (defined('APP_ENV') && APP_ENV === 'production') {
            sendHttp10Response(500);
            exit;
        }
    });
    
    // Set shutdown handler voor fatal errors
    register_shutdown_function(function() {
        $error = error_get_last();
        if ($error !== NULL && in_array($error['type'], [E_ERROR, E_CORE_ERROR, E_COMPILE_ERROR, E_PARSE])) {
            $errorMsg = "Fatal Error [" . $error['type'] . "]: " . $error['message'] . "\n";
            $errorMsg .= "File: " . $error['file'] . "\n";
            $errorMsg .= "Line: " . $error['line'] . "\n";
            error_log($errorMsg, 3, __DIR__ . '/error.log');
        }
    });
}

/**
 * Haal client IP adres op (met proxy support)
 * @return string IP adres
 */
function getClientIp() {
    $ipKeys = [
        'HTTP_CF_CONNECTING_IP', // Cloudflare
        'HTTP_X_REAL_IP',        // Nginx proxy
        'HTTP_X_FORWARDED_FOR',  // Standard proxy header
        'REMOTE_ADDR'            // Fallback
    ];
    
    foreach ($ipKeys as $key) {
        if (!empty($_SERVER[$key])) {
            $ip = $_SERVER[$key];
            // X-Forwarded-For kan meerdere IPs bevatten (client, proxy1, proxy2)
            if (strpos($ip, ',') !== false) {
                $ips = explode(',', $ip);
                $ip = trim($ips[0]); // Neem eerste IP (originele client)
            }
            
            // Valideer IP
            if (filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_NO_PRIV_RANGE | FILTER_FLAG_NO_RES_RANGE)) {
                return $ip;
            }
        }
    }
    
    // Fallback naar REMOTE_ADDR
    return isset($_SERVER['REMOTE_ADDR']) ? $_SERVER['REMOTE_ADDR'] : '0.0.0.0';
}

/**
 * Check rate limit voor huidige client
 * @return bool True als request toegestaan is, false als limiet overschreden
 */
function checkRateLimit() {
    if (!defined('RATE_LIMIT_ENABLED') || !RATE_LIMIT_ENABLED) {
        return true; // Rate limiting uitgeschakeld
    }
    
    $ip = getClientIp();
    $requests = defined('RATE_LIMIT_REQUESTS') ? RATE_LIMIT_REQUESTS : 60;
    $window = defined('RATE_LIMIT_WINDOW') ? RATE_LIMIT_WINDOW : 60;
    
    $rateLimitFile = CACHE_DIR . '/ratelimit_' . md5($ip) . '.txt';
    $now = time();
    
    // Lees bestaande rate limit data
    $data = [];
    if (file_exists($rateLimitFile)) {
        $content = @file_get_contents($rateLimitFile);
        if ($content !== false) {
            $data = @json_decode($content, true);
            if (!is_array($data)) {
                $data = [];
            }
        }
    }
    
    // Clean oude entries
    $data = array_filter($data, function($timestamp) use ($now, $window) {
        return ($now - $timestamp) < $window;
    });
    
    // Check of limiet overschreden is
    if (count($data) >= $requests) {
        logSecurityEvent('rate_limit_exceeded', ['ip' => $ip, 'requests' => count($data), 'limit' => $requests]);
        sendHttp10Response(429);
        header('Retry-After: ' . $window);
        $errorHtml = "<html><head><title>Too Many Requests</title></head><body>\n";
        $errorHtml .= "<h1>429 Too Many Requests</h1>\n";
        $errorHtml .= "<p>You have made too many requests. Please try again later.</p>\n";
        $errorHtml .= "</body></html>\n";
        setHttp10Headers(strlen($errorHtml));
        echo $errorHtml;
        return false;
    }
    
    // Voeg huidige request toe
    $data[] = $now;
    
    // Sla op
    @file_put_contents($rateLimitFile, json_encode($data), LOCK_EX);
    
    return true;
}

/**
 * Parse memory limit string naar bytes
 * @param string $memoryLimit Memory limit string (bijv. "128M", "512K")
 * @return int Memory limit in bytes
 */
function parseMemoryLimit($memoryLimit) {
    $memoryLimit = trim($memoryLimit);
    $last = strtolower($memoryLimit[strlen($memoryLimit) - 1]);
    $value = (int)$memoryLimit;
    
    switch ($last) {
        case 'g':
            $value *= 1024;
            // fall through
        case 'm':
            $value *= 1024;
            // fall through
        case 'k':
            $value *= 1024;
    }
    
    return $value;
}

/**
 * Sanitize en valideer URL
 * @param string $url URL om te sanitizen
 * @return string|false Sanitized URL of false bij invalid
 */
function sanitizeUrl($url) {
    // Check maximum lengte (soepeler voor HTTP/1.0 browsers)
    $maxLength = MAX_URL_LENGTH * 2; // Verdubbel limiet voor oude browsers
    if (strlen($url) > $maxLength) {
        return false;
    }
    
    // Decode en re-encode om double encoding te voorkomen
    $url = urldecode($url);
    
    // Verwijder control characters (behalve whitespace)
    $url = preg_replace('/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/', '', $url);
    
    // Trim whitespace
    $url = trim($url);
    
    // Als URL geen protocol heeft, voeg http:// toe (voor HTTP/1.0 browsers)
    if (!preg_match('/^https?:\/\//', $url)) {
        // Check of het een domain lijkt te zijn
        if (preg_match('/^[a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,}/', $url)) {
            $url = 'http://' . $url;
        }
    }
    
    // Probeer URL te parsen
    $parsed = parse_url($url);
    
    // Als parse_url faalt, probeer handmatige reparatie
    if ($parsed === false) {
        // Probeer basis reparatie: voeg http:// toe als het nog niet heeft
        if (!preg_match('/^https?:\/\//', $url)) {
            $url = 'http://' . $url;
            $parsed = parse_url($url);
        }
        
        // Als het nog steeds faalt, gebruik regex validatie als fallback
        if ($parsed === false) {
            // Basis check: moet eruit zien als een URL
            if (preg_match('/^https?:\/\/[a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,}/', $url)) {
                // Accepteer URL ook al faalt parse_url (voor edge cases)
                return $url;
            }
            return false;
        }
    }
    
    // Rebuild URL met proper encoding
    $scheme = isset($parsed['scheme']) ? $parsed['scheme'] . '://' : 'http://';
    $host = isset($parsed['host']) ? $parsed['host'] : '';
    $port = isset($parsed['port']) ? ':' . $parsed['port'] : '';
    $path = isset($parsed['path']) ? $parsed['path'] : '/';
    $query = isset($parsed['query']) ? '?' . $parsed['query'] : '';
    $fragment = isset($parsed['fragment']) ? '#' . $parsed['fragment'] : '';
    
    // Encode path, query en fragment (maar wees voorzichtig met re-encoding)
    // Voor HTTP/1.0 browsers: behoud originele encoding waar mogelijk
    if ($path && $path !== '/') {
        // Alleen encode als echt nodig (behoud originele encoding)
        $pathParts = explode('/', $path);
        $encodedParts = [];
        foreach ($pathParts as $part) {
            // Als part al encoded lijkt, behoud het
            if (preg_match('/%[0-9A-Fa-f]{2}/', $part)) {
                $encodedParts[] = $part;
            } else {
                $encodedParts[] = rawurlencode($part);
            }
        }
        $path = implode('/', $encodedParts);
    }
    
    return $scheme . $host . $port . $path . $query . $fragment;
}

/**
 * Stuur HTTP/1.0 status response
 * @param int $code HTTP status code
 * @param string|null $statusMessage Optionele status message (default wordt gebruikt als null)
 */
function sendHttp10Response($code, $statusMessage = null) {
    $statusMessages = [
        200 => 'OK',
        204 => 'No Content',
        302 => 'Found',
        400 => 'Bad Request',
        403 => 'Forbidden',
        404 => 'Not Found',
        413 => 'Request Entity Too Large',
        429 => 'Too Many Requests',
        500 => 'Internal Server Error'
    ];
    
    $message = $statusMessage ?: (isset($statusMessages[$code]) ? $statusMessages[$code] : 'OK');
    header('HTTP/1.0 ' . $code . ' ' . $message, true);
}

/**
 * Stel standaard HTTP/1.0 headers in
 * @param int|null $contentLength Content-Length in bytes (optioneel)
 */
function setHttp10Headers($contentLength = null) {
    header('Connection: close');
    if ($contentLength !== null) {
        header('Content-Length: ' . $contentLength);
    }
}

/**
 * Stel HTTP Security Headers in (HTTP/1.0 compatible)
 */
function setSecurityHeaders() {
    // Alleen instellen als headers nog niet zijn verzonden
    if (headers_sent()) {
        return;
    }
    
    // HTTP/1.0 compatible headers
    header('Connection: close');
    
    // X-Frame-Options: Voorkomt clickjacking
    if (!headers_sent() && !isset($_SERVER['HTTP_X_FRAME_OPTIONS'])) {
        header('X-Frame-Options: DENY');
    }
    
    // X-Content-Type-Options: Voorkomt MIME type sniffing
    if (!headers_sent() && !isset($_SERVER['HTTP_X_CONTENT_TYPE_OPTIONS'])) {
        header('X-Content-Type-Options: nosniff');
    }
    
    // X-XSS-Protection: Extra XSS bescherming voor oude browsers
    if (!headers_sent() && !isset($_SERVER['HTTP_X_XSS_PROTECTION'])) {
        header('X-XSS-Protection: 1; mode=block');
    }
    
    // Referrer-Policy: Beperkt referrer informatie
    if (!headers_sent() && !isset($_SERVER['HTTP_REFERRER_POLICY'])) {
        header('Referrer-Policy: no-referrer');
    }
    
    // Content-Security-Policy: Basis CSP (kan later uitgebreid worden)
    // Voor een proxy is dit lastig omdat we externe content laden, dus basis CSP
    if (!headers_sent() && !isset($_SERVER['HTTP_CONTENT_SECURITY_POLICY'])) {
        header("Content-Security-Policy: default-src 'self'; script-src 'none'; object-src 'none';");
    }
}

/**
 * Valideer search query
 * @param string $query Search query om te valideren
 * @return bool True als query geldig is, false anders
 */
function validateSearchQuery($query) {
    if (empty($query) || !is_string($query)) {
        return false;
    }
    
    // Check maximum lengte
    if (strlen($query) > MAX_SEARCH_QUERY_LENGTH) {
        logSecurityEvent('search_query_too_long', ['length' => strlen($query), 'max' => MAX_SEARCH_QUERY_LENGTH]);
        return false;
    }
    
    // Verwijder control characters
    $cleanQuery = preg_replace('/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/', '', $query);
    if ($cleanQuery !== $query) {
        logSecurityEvent('search_query_control_chars', ['query' => substr($query, 0, 100)]);
        return false;
    }
    
    // Check voor gevaarlijke patterns (basis check)
    $dangerousPatterns = [
        '/<script/i',
        '/javascript:/i',
        '/on\w+\s*=/i', // onclick, onerror, etc.
        '/data:text\/html/i',
        '/vbscript:/i'
    ];
    
    foreach ($dangerousPatterns as $pattern) {
        if (preg_match($pattern, $query)) {
            logSecurityEvent('search_query_dangerous_pattern', ['pattern' => $pattern, 'query' => substr($query, 0, 100)]);
            return false;
        }
    }
    
    return true;
}

/**
 * Check request size limits
 * @return bool True als request size OK is, false als te groot
 */
function checkRequestSize() {
    $maxSize = defined('MAX_REQUEST_SIZE') ? MAX_REQUEST_SIZE : 1024 * 1024;
    
    // Check POST data size
    if ($_SERVER['REQUEST_METHOD'] === 'POST' && isset($_SERVER['CONTENT_LENGTH'])) {
        $contentLength = (int)$_SERVER['CONTENT_LENGTH'];
        if ($contentLength > $maxSize) {
            logSecurityEvent('request_size_exceeded', ['size' => $contentLength, 'max' => $maxSize, 'type' => 'POST']);
            return false;
        }
    }
    
    // Check GET parameters size (soepeler voor HTTP/1.0 browsers - 16KB in plaats van 8KB)
    // Oude browsers kunnen langere URLs hebben door encoding verschillen
    $queryString = isset($_SERVER['QUERY_STRING']) ? $_SERVER['QUERY_STRING'] : '';
    $queryStringMax = 16384; // 16KB voor HTTP/1.0 compatibiliteit
    if (strlen($queryString) > $queryStringMax) {
        logSecurityEvent('request_size_exceeded', ['size' => strlen($queryString), 'max' => $queryStringMax, 'type' => 'GET']);
        return false;
    }
    
    // Check total request URI length (soepeler voor HTTP/1.0 browsers)
    $requestUri = isset($_SERVER['REQUEST_URI']) ? $_SERVER['REQUEST_URI'] : '';
    $uriMax = 16384; // 16KB voor HTTP/1.0 compatibiliteit
    if (strlen($requestUri) > $uriMax) {
        logSecurityEvent('request_size_exceeded', ['size' => strlen($requestUri), 'max' => $uriMax, 'type' => 'URI']);
        return false;
    }
    
    return true;
}

/**
 * Log security event
 * @param string $eventType Type van security event
 * @param array $details Extra details over het event
 */
function logSecurityEvent($eventType, $details = []) {
    $logFile = __DIR__ . '/security.log';
    $timestamp = date('Y-m-d H:i:s');
    $ip = getClientIp();
    $userAgent = isset($_SERVER['HTTP_USER_AGENT']) ? $_SERVER['HTTP_USER_AGENT'] : 'Unknown';
    
    $logEntry = "[$timestamp] [$ip] [$eventType]";
    if (!empty($details)) {
        $logEntry .= ' ' . json_encode($details);
    }
    $logEntry .= " [UA: $userAgent]\n";
    
    @file_put_contents($logFile, $logEntry, FILE_APPEND | LOCK_EX);
}

/**
 * Check voor redirect loops
 * @param array $visitedUrls Array van bezochte URLs
 * @param string $newUrl Nieuwe URL om te checken
 * @return bool True als er een loop is gedetecteerd
 */
function checkRedirectLoop($visitedUrls, $newUrl) {
    // Normaliseer URL voor vergelijking (verwijder fragment en query parameters die niet relevant zijn)
    $normalized = parse_url($newUrl);
    if (!$normalized) {
        return false;
    }
    
    $normalizedUrl = '';
    if (isset($normalized['scheme'])) {
        $normalizedUrl .= $normalized['scheme'] . '://';
    }
    if (isset($normalized['host'])) {
        $normalizedUrl .= strtolower($normalized['host']);
    }
    if (isset($normalized['port'])) {
        $normalizedUrl .= ':' . $normalized['port'];
    }
    if (isset($normalized['path'])) {
        $normalizedUrl .= $normalized['path'];
    }
    
    // Check of deze URL al is bezocht
    foreach ($visitedUrls as $visited) {
        $visitedNormalized = parse_url($visited);
        if (!$visitedNormalized) {
            continue;
        }
        
        $visitedUrl = '';
        if (isset($visitedNormalized['scheme'])) {
            $visitedUrl .= $visitedNormalized['scheme'] . '://';
        }
        if (isset($visitedNormalized['host'])) {
            $visitedUrl .= strtolower($visitedNormalized['host']);
        }
        if (isset($visitedNormalized['port'])) {
            $visitedUrl .= ':' . $visitedNormalized['port'];
        }
        if (isset($visitedNormalized['path'])) {
            $visitedUrl .= $visitedNormalized['path'];
        }
        
        if ($normalizedUrl === $visitedUrl && !empty($normalizedUrl)) {
            return true; // Loop gedetecteerd
        }
    }
    
    return false;
}

/**
 * Valideer Content-Length header tegen daadwerkelijke content size
 * @param string $content Content data
 * @param array $headers Response headers
 * @return bool True als Content-Length klopt of niet aanwezig, false als mismatch
 */
function validateContentLength($content, $headers = []) {
    // Check Content-Length header
    $contentLength = null;
    foreach ($headers as $key => $value) {
        if (strtolower($key) === 'content-length' || 
            (is_numeric($key) && preg_match('/^Content-Length:\s*(.+)$/i', $value, $matches))) {
            $contentLength = is_numeric($key) ? (int)trim($matches[1]) : (int)$value;
            break;
        }
    }
    
    // Als Content-Length header aanwezig is, valideer tegen daadwerkelijke size
    if ($contentLength !== null) {
        $actualSize = strlen($content);
        // Toelaatbare afwijking: 10% of 1KB (voor compressie/encoding verschillen)
        $tolerance = max($contentLength * 0.1, 1024);
        
        if (abs($actualSize - $contentLength) > $tolerance) {
            logSecurityEvent('content_length_mismatch', [
                'expected' => $contentLength,
                'actual' => $actualSize,
                'difference' => abs($actualSize - $contentLength)
            ]);
            return false;
        }
    }
    
    return true;
}

/**
 * Haal image mode op uit URL parameter
 * @return string 'links' of 'inline'
 */
function getImageMode() {
    // Check of er meerdere img parameters zijn (kan gebeuren door URL building)
    // Pak de laatste waarde, of check of 'inline' ergens voorkomt
    if (isset($_GET['img'])) {
        $imgValue = $_GET['img'];
        // Als het een array is (meerdere parameters), pak de laatste
        if (is_array($imgValue)) {
            $imgValue = end($imgValue);
        }
        return $imgValue === 'inline' ? 'inline' : 'links';
    }
    // Check ook in REQUEST_URI voor het geval dat
    if (isset($_SERVER['REQUEST_URI']) && strpos($_SERVER['REQUEST_URI'], 'img=inline') !== false) {
        return 'inline';
    }
    return 'links';
}

/**
 * Voeg image mode parameter toe aan URL
 * @param string $url Basis URL
 * @param string $imageMode Image mode ('links' of 'inline')
 * @return string URL met image mode parameter
 */
function buildUrlWithImageMode($url, $imageMode = null) {
    if ($imageMode === null) {
        $imageMode = getImageMode();
    }
    
    // Parse de URL om query parameters te behouden
    $parsed = parse_url($url);
    $scheme = isset($parsed['scheme']) ? $parsed['scheme'] . '://' : '';
    $host = isset($parsed['host']) ? $parsed['host'] : '';
    $port = isset($parsed['port']) ? ':' . $parsed['port'] : '';
    $path = isset($parsed['path']) ? $parsed['path'] : '';
    $query = isset($parsed['query']) ? $parsed['query'] : '';
    $fragment = isset($parsed['fragment']) ? '#' . $parsed['fragment'] : '';
    
    // Parse bestaande query parameters
    $params = [];
    if (!empty($query)) {
        parse_str($query, $params);
    }
    
    // Update of voeg img parameter toe
    $params['img'] = $imageMode;
    
    // Rebuild query string
    $newQuery = http_build_query($params);
    
    // Rebuild URL
    return $scheme . $host . $port . $path . ($newQuery ? '?' . $newQuery : '') . $fragment;
}

/**
 * Normaliseer image URL naar absolute URL
 * @param string $url Image URL (kan relatief, protocol-relative, of absoluut zijn)
 * @param string $baseUrl Base URL van de pagina waar de image vandaan komt
 * @return string Genormaliseerde absolute URL
 */
function normalizeImageUrl($url, $baseUrl) {
    // Als al absoluut met protocol, retourneer zoals is
    if (preg_match('/^https?:\/\//', $url)) {
        return $url;
    }
    
    // Parse base URL
    $baseParts = parse_url($baseUrl);
    $scheme = isset($baseParts['scheme']) ? $baseParts['scheme'] : 'https';
    $host = isset($baseParts['host']) ? $baseParts['host'] : '';
    $path = isset($baseParts['path']) ? dirname($baseParts['path']) : '/';
    
    // Protocol-relative URL (//example.com/image.jpg)
    if (preg_match('/^\/\//', $url)) {
        return $scheme . ':' . $url;
    }
    
    // Absolute path (/image.jpg)
    if (preg_match('/^\//', $url)) {
        return $scheme . '://' . $host . $url;
    }
    
    // Relatieve URL (image.jpg of ../image.jpg)
    // Normaliseer path
    $path = rtrim($path, '/') . '/';
    $urlParts = explode('/', $path . $url);
    $normalized = [];
    
    foreach ($urlParts as $part) {
        if ($part === '' || $part === '.') {
            continue;
        } elseif ($part === '..') {
            array_pop($normalized);
        } else {
            $normalized[] = $part;
        }
    }
    
    $normalizedPath = '/' . implode('/', $normalized);
    return $scheme . '://' . $host . $normalizedPath;
}

/**
 * Verwijder dropdown/interlanguage selector content (zoals Wikipedia taal dropdowns)
 * @param string $html HTML content
 * @return string HTML zonder dropdown content
 */
function stripDropdownContent($html) {
    // Verwijder interlanguage selector dropdowns (Wikipedia style)
    // Match: input checkbox met interlanguage-selector class, gevolgd door label en dropdown content
    $html = preg_replace('/<input[^>]*class="[^"]*interlanguage-selector[^"]*"[^>]*>.*?<\/div>\s*<\/div>/is', '', $html);
    
    // Verwijder vector dropdown content (Wikipedia Vector theme)
    $html = preg_replace('/<div[^>]*class="[^"]*vector-dropdown-content[^"]*"[^>]*>.*?<\/div>/is', '', $html);
    
    // Verwijder interlanguage link lists (als ze nog over zijn)
    // Match ul met veel interlanguage-link items
    $html = preg_replace('/<ul[^>]*class="[^"]*vector-menu-content-list[^"]*"[^>]*>.*?<\/ul>/is', '', $html);
    
    // Verwijder losse interlanguage link containers
    $html = preg_replace('/<div[^>]*class="[^"]*mw-interlanguage-selector[^"]*"[^>]*>.*?<\/div>/is', '', $html);
    
    // Verwijder labels met dropdown-label class die interlanguage selectors zijn
    $html = preg_replace('/<label[^>]*class="[^"]*vector-dropdown-label[^"]*"[^>]*>.*?<\/label>/is', '', $html);
    
    // Verwijder losse interlanguage-link items (als ze nog over zijn na bovenstaande)
    $html = preg_replace('/<li[^>]*class="[^"]*interlanguage-link[^"]*"[^>]*>.*?<\/li>/is', '', $html);
    
    return $html;
}

/**
 * Strip moderne HTML tags die oude browsers niet ondersteunen
 * @param string $html HTML content
 * @return string HTML zonder moderne tags
 */
function stripModernTags($html) {
    // Verwijder eerst dropdown/interlanguage content
    $html = stripDropdownContent($html);
    
    // Strip script, style, noscript, iframe, svg tags en hun content
    $html = preg_replace('/<script\b[^>]*>.*?<\/script>/is', '', $html);
    $html = preg_replace('/<style\b[^>]*>.*?<\/style>/is', '', $html);
    $html = preg_replace('/<noscript\b[^>]*>.*?<\/noscript>/is', '', $html);
    $html = preg_replace('/<iframe\b[^>]*>.*?<\/iframe>/is', '', $html);
    $html = preg_replace('/<svg\b[^>]*>.*?<\/svg>/is', '', $html);
    
    return $html;
}

/**
 * Behoud font color attributen in content
 * @param string $html HTML content
 * @param string $originalHtml Originele HTML om font colors uit te extraheren
 * @return string HTML met behouden font colors
 */
function preserveFontColors($html, $originalHtml = '') {
    if (empty($originalHtml)) {
        return $html;
    }
    
    // Extract alle font tags met color attributen uit originele HTML
    preg_match_all('/<font[^>]*color\s*=\s*["\']([^"\']+)["\'][^>]*>/i', $originalHtml, $fontMatches, PREG_OFFSET_CAPTURE);
    
    // Als er font tags met colors zijn, probeer ze te behouden in de content
    // Dit is een basis implementatie - font tags zouden al behouden moeten blijven via strip_tags
    // Maar we kunnen ze verifiëren en aanvullen indien nodig
    
    return $html;
}

/**
 * Converteer moderne HTML tags naar oude tags
 * @param string $html HTML content
 * @return string HTML met geconverteerde tags
 */
function convertModernTags($html) {
    $html = preg_replace('/<strong\b[^>]*>/i', '<b>', $html);
    $html = preg_replace('/<\/strong>/i', '</b>', $html);
    $html = preg_replace('/<em\b[^>]*>/i', '<i>', $html);
    $html = preg_replace('/<\/em>/i', '</i>', $html);
    
    return $html;
}

/**
 * Extract achtergrondkleur en tekstkleur uit HTML
 * @param string $html Originele HTML
 * @return array ['bgcolor' => string|null, 'text' => string|null, 'link' => string|null]
 */
function extractColors($html) {
    $colors = ['bgcolor' => null, 'text' => null, 'link' => null];
    
    // Extract uit body tag
    if (preg_match('/<body[^>]*>/i', $html, $bodyMatch)) {
        $bodyTag = $bodyMatch[0];
        
        // Extract bgcolor attribuut
        if (preg_match('/bgcolor\s*=\s*["\']?([^"\'\s>]+)/i', $bodyTag, $bgMatch)) {
            $colors['bgcolor'] = trim($bgMatch[1]);
        }
        
        // Extract text attribuut
        if (preg_match('/text\s*=\s*["\']?([^"\'\s>]+)/i', $bodyTag, $textMatch)) {
            $colors['text'] = trim($textMatch[1]);
        }
        
        // Extract link attribuut
        if (preg_match('/link\s*=\s*["\']?([^"\'\s>]+)/i', $bodyTag, $linkMatch)) {
            $colors['link'] = trim($linkMatch[1]);
        }
        
        // Extract uit style attribuut
        if (preg_match('/style\s*=\s*["\']([^"\']+)["\']/i', $bodyTag, $styleMatch)) {
            $style = $styleMatch[1];
            
            // Extract background-color
            if (preg_match('/background-color\s*:\s*([^;]+)/i', $style, $bgStyleMatch)) {
                $colors['bgcolor'] = trim($bgStyleMatch[1]);
            }
            
            // Extract color
            if (preg_match('/color\s*:\s*([^;]+)/i', $style, $colorStyleMatch)) {
                $colors['text'] = trim($colorStyleMatch[1]);
            }
        }
    }
    
    // Extract uit HTML tag (oude HTML)
    if (preg_match('/<html[^>]*>/i', $html, $htmlMatch)) {
        $htmlTag = $htmlMatch[0];
        
        if (preg_match('/bgcolor\s*=\s*["\']?([^"\'\s>]+)/i', $htmlTag, $bgMatch)) {
            if ($colors['bgcolor'] === null) {
                $colors['bgcolor'] = trim($bgMatch[1]);
            }
        }
        
        if (preg_match('/text\s*=\s*["\']?([^"\'\s>]+)/i', $htmlTag, $textMatch)) {
            if ($colors['text'] === null) {
                $colors['text'] = trim($textMatch[1]);
            }
        }
    }
    
    return $colors;
}

/**
 * Check of een kleur licht is (wit, lichtgrijs, etc.)
 * @param string $color Kleur (hex, rgb, of named color)
 * @return bool True als kleur licht is
 */
function isLightColor($color) {
    if (empty($color)) {
        return false;
    }
    
    $color = strtolower(trim($color));
    
    // Named colors die licht zijn
    $lightColors = ['white', '#ffffff', '#fff', 'rgb(255,255,255)', 'rgb(255, 255, 255)'];
    if (in_array($color, $lightColors)) {
        return true;
    }
    
    // Hex colors
    if (preg_match('/^#([0-9a-f]{3}|[0-9a-f]{6})$/i', $color)) {
        // Converteer 3-digit naar 6-digit
        if (strlen($color) === 4) {
            $color = '#' . $color[1] . $color[1] . $color[2] . $color[2] . $color[3] . $color[3];
        }
        
        $r = hexdec(substr($color, 1, 2));
        $g = hexdec(substr($color, 3, 2));
        $b = hexdec(substr($color, 5, 2));
        
        // Bereken luminance (relatieve helderheid)
        $luminance = (0.299 * $r + 0.587 * $g + 0.114 * $b) / 255;
        
        // Als luminance > 0.7, is het een lichte kleur
        return $luminance > 0.7;
    }
    
    // RGB colors
    if (preg_match('/rgb\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)/i', $color, $rgbMatch)) {
        $r = (int)$rgbMatch[1];
        $g = (int)$rgbMatch[2];
        $b = (int)$rgbMatch[3];
        
        $luminance = (0.299 * $r + 0.587 * $g + 0.114 * $b) / 255;
        return $luminance > 0.7;
    }
    
    return false;
}

/**
 * Clean speciale karakters die oude browsers niet kunnen weergeven
 * @param string $html HTML content
 * @return string HTML met geconverteerde karakters
 */
function cleanSpecialCharacters($html) {
    // Smart quotes (gebruik hex codes om encoding problemen te voorkomen)
    $html = str_replace(["\xE2\x80\x98", "\xE2\x80\x99", "\xE2\x80\x9C", "\xE2\x80\x9D"], ["'", "'", '"', '"'], $html);
    
    // Em-dash en en-dash
    $html = str_replace(["\xE2\x80\x94", "\xE2\x80\x93"], ['--', '-'], $html);
    
    // Ellipsis
    $html = str_replace("\xE2\x80\xA6", '...', $html);
    
    return $html;
}

/**
 * Converteer speciale karakters (umlauts, etc.) naar HTML entities voor HTML 2.0 compatibiliteit
 * Converteert alleen tekst tussen HTML tags, niet de tags zelf
 * @param string $html HTML content
 * @return string HTML met geconverteerde karakters als HTML entities
 */
function convertToHtmlEntities($html) {
    // Eerst normaliseer de encoding naar UTF-8 als het nog niet UTF-8 is
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
                // Mogelijk verkeerd geïnterpreteerde UTF-8, probeer te repareren
                $html = mb_convert_encoding($html, 'UTF-8', 'ISO-8859-1');
            }
        }
    }
    
    // Converteer alleen tekst tussen tags, niet de tags zelf
    // Dit voorkomt dat HTML tags worden ge-escaped
    return preg_replace_callback(
        '/([^<]+)|(<[^>]*>)/',
        function($matches) {
            // Als het een tag is, behoud deze zoals die is
            if (isset($matches[2]) && !empty($matches[2])) {
                return $matches[2];
            }
            
            // Als het tekst is, converteer naar HTML entities
            $text = isset($matches[1]) ? $matches[1] : '';
            if (empty($text)) {
                return '';
            }
            
            // Zorg dat tekst UTF-8 is voordat we converteren
            if (function_exists('mb_convert_encoding')) {
                // Probeer te detecteren en normaliseren
                $detected = mb_detect_encoding($text, ['UTF-8', 'ISO-8859-1', 'Windows-1252'], true);
                if ($detected && $detected !== 'UTF-8') {
                    $text = mb_convert_encoding($text, 'UTF-8', $detected);
                } elseif (!$detected) {
                    // Als encoding niet gedetecteerd kan worden, probeer UTF-8 te forceren
                    // Check of het mogelijk verkeerd geïnterpreteerde UTF-8 is (zoals "GefÃ¼hl")
                    if (preg_match('/[\xC0-\xFF][\x80-\xBF]/', $text)) {
                        // Mogelijk verkeerd geïnterpreteerde UTF-8, probeer te repareren
                        $text = mb_convert_encoding($text, 'UTF-8', 'ISO-8859-1');
                    }
                }
            }
            
            // Converteer UTF-8 tekst naar HTML entities voor HTML 2.0
            // ENT_QUOTES converteert quotes, ENT_SUBSTITUTE vervangt ongeldige karakters
            // ENT_HTML401 gebruikt HTML 4.01 entity set (compatibel met HTML 2.0)
            // Gebruik UTF-8 als input encoding - htmlentities zal UTF-8 karakters converteren naar entities
            return htmlentities($text, ENT_QUOTES | ENT_SUBSTITUTE | ENT_HTML401, 'UTF-8', false);
        },
        $html
    );
}

/**
 * Extract image dimensions uit HTML en CSS
 * @param string $imgTag Volledige img tag HTML
 * @param string $originalHtml Originele HTML (voor CSS parsing)
 * @return array ['width' => int|null, 'height' => int|null]
 */
function extractImageDimensions($imgTag, $originalHtml = '') {
    $dimensions = ['width' => null, 'height' => null];
    
    // Extract HTML attributen
    if (preg_match('/width\s*=\s*["\']?(\d+)/i', $imgTag, $widthMatch)) {
        $dimensions['width'] = (int)$widthMatch[1];
    }
    
    if (preg_match('/height\s*=\s*["\']?(\d+)/i', $imgTag, $heightMatch)) {
        $dimensions['height'] = (int)$heightMatch[1];
    }
    
    // Extract inline style
    if (preg_match('/style\s*=\s*["\']([^"\']*)["\']/i', $imgTag, $styleMatch)) {
        $style = $styleMatch[1];
        if (preg_match('/width\s*:\s*(\d+)px/i', $style, $widthMatch)) {
            $dimensions['width'] = (int)$widthMatch[1];
        }
        if (preg_match('/height\s*:\s*(\d+)px/i', $style, $heightMatch)) {
            $dimensions['height'] = (int)$heightMatch[1];
        }
        // Check max-width en max-height
        if (preg_match('/max-width\s*:\s*(\d+)px/i', $style, $maxWidthMatch)) {
            if ($dimensions['width'] === null || $dimensions['width'] > (int)$maxWidthMatch[1]) {
                $dimensions['width'] = (int)$maxWidthMatch[1];
            }
        }
        if (preg_match('/max-height\s*:\s*(\d+)px/i', $style, $maxHeightMatch)) {
            if ($dimensions['height'] === null || $dimensions['height'] > (int)$maxHeightMatch[1]) {
                $dimensions['height'] = (int)$maxHeightMatch[1];
            }
        }
    }
    
    // Parse CSS uit style tags (als originalHtml beschikbaar is)
    if (!empty($originalHtml)) {
        // Extract class en id uit img tag
        $classes = [];
        $id = '';
        
        if (preg_match('/class\s*=\s*["\']([^"\']+)["\']/i', $imgTag, $classMatch)) {
            $classes = explode(' ', $classMatch[1]);
        }
        
        if (preg_match('/id\s*=\s*["\']([^"\']+)["\']/i', $imgTag, $idMatch)) {
            $id = $idMatch[1];
        }
        
        // Parse style tags
        preg_match_all('/<style[^>]*>(.*?)<\/style>/is', $originalHtml, $styleMatches);
        foreach ($styleMatches[1] as $css) {
            // Parse CSS rules (basis implementatie)
            // Zoek naar img selectors, class selectors, en id selectors
            $selectors = ['img'];
            
            if (!empty($classes)) {
                $selectors[] = 'img.' . implode(', img.', $classes);
                foreach ($classes as $class) {
                    $selectors[] = '.' . $class;
                    $selectors[] = 'img.' . $class;
                }
            }
            
            if (!empty($id)) {
                $selectors[] = 'img#' . $id;
                $selectors[] = '#' . $id;
            }
            
            foreach ($selectors as $selector) {
                $pattern = '/' . preg_quote($selector, '/') . '\s*\{[^}]*width\s*:\s*(\d+)px[^}]*\}/i';
                if (preg_match($pattern, $css, $match)) {
                    if ($dimensions['width'] === null || $dimensions['width'] > (int)$match[1]) {
                        $dimensions['width'] = (int)$match[1];
                    }
                }
                
                $pattern = '/' . preg_quote($selector, '/') . '\s*\{[^}]*height\s*:\s*(\d+)px[^}]*\}/i';
                if (preg_match($pattern, $css, $match)) {
                    if ($dimensions['height'] === null || $dimensions['height'] > (int)$match[1]) {
                        $dimensions['height'] = (int)$match[1];
                    }
                }
                
                // Check max-width en max-height in CSS
                $pattern = '/' . preg_quote($selector, '/') . '\s*\{[^}]*max-width\s*:\s*(\d+)px[^}]*\}/i';
                if (preg_match($pattern, $css, $match)) {
                    if ($dimensions['width'] === null || $dimensions['width'] > (int)$match[1]) {
                        $dimensions['width'] = (int)$match[1];
                    }
                }
                
                $pattern = '/' . preg_quote($selector, '/') . '\s*\{[^}]*max-height\s*:\s*(\d+)px[^}]*\}/i';
                if (preg_match($pattern, $css, $match)) {
                    if ($dimensions['height'] === null || $dimensions['height'] > (int)$match[1]) {
                        $dimensions['height'] = (int)$match[1];
                    }
                }
            }
        }
    }
    
    return $dimensions;
}

/**
 * Check of image verborgen moet worden (32x32 of kleiner, CSS-aware)
 * @param string $imgTag Volledige img tag HTML
 * @param string $url Image URL (voor pattern matching)
 * @param string $originalHtml Originele HTML (voor CSS parsing)
 * @return bool True als image verborgen moet worden
 */
function shouldHideImage($imgTag, $url = '', $originalHtml = '') {
    $dimensions = extractImageDimensions($imgTag, $originalHtml);
    
    // Check dimensions
    if ($dimensions['width'] !== null && $dimensions['width'] <= MIN_IMAGE_SIZE) {
        return true;
    }
    
    if ($dimensions['height'] !== null && $dimensions['height'] <= MIN_IMAGE_SIZE) {
        return true;
    }
    
    // Als beide dimensions bekend zijn en beide <= 32
    if ($dimensions['width'] !== null && $dimensions['height'] !== null) {
        if ($dimensions['width'] <= MIN_IMAGE_SIZE && $dimensions['height'] <= MIN_IMAGE_SIZE) {
            return true;
        }
    }
    
    // Check URL patterns die suggereren kleine images
    // Let op: '/thumb/' is verwijderd omdat Wikipedia en andere sites dit gebruiken voor thumbnails die groter kunnen zijn
    $smallImagePatterns = ['/icon/', '/avatar/', '/favicon', '/spacer', '/pixel'];
    foreach ($smallImagePatterns as $pattern) {
        if (stripos($url, $pattern) !== false) {
            return true;
        }
    }
    
    return false;
}

/**
 * Maak stream context voor HTTP requests
 * @param string $method HTTP method (GET, HEAD, etc.)
 * @return resource Stream context
 */
function createStreamContext($method = 'GET') {
    $timeout = defined('REQUEST_TIMEOUT') ? REQUEST_TIMEOUT : 30;
    $maxRedirects = defined('MAX_REDIRECT_DEPTH') ? MAX_REDIRECT_DEPTH : 5;
    
    return stream_context_create([
        'http' => [
            'method' => $method,
            'header' => "User-Agent: " . USER_AGENT . "\r\n",
            'follow_location' => 1,
            'max_redirects' => $maxRedirects,
            'timeout' => $timeout,
            'ignore_errors' => true
        ]
    ]);
}

/**
 * Render navigation bar (shared component)
 * @param string $imageMode Current image mode
 * @return string HTML for navigation bar
 */
function renderNavigation($imageMode = null) {
    if ($imageMode === null) {
        $imageMode = getImageMode();
    }
    
    $basePath = getBasePath();
    $baseUrl = getBaseUrl();
    $homeUrl = $baseUrl . '/index.php';
    
    // Add image mode parameter to home URL
    $homeUrl = buildUrlWithImageMode($homeUrl, $imageMode);
    
    // Link tekst is altijd "RetroWEB"
    $linkText = 'RetroWEB';
    
    // Gebruik absolute URL voor toggle links (voor oude browsers)
    // Bouw URL op basis van huidige request met alle parameters
    $currentPath = isset($_SERVER['SCRIPT_NAME']) ? $_SERVER['SCRIPT_NAME'] : '/proxy.php';
    // Als het pad niet begint met base path, voeg het toe
    if ($basePath !== '/' && strpos($currentPath, $basePath) !== 0) {
        $currentPath = $basePath . $currentPath;
    }
    $currentUri = $baseUrl . $currentPath;
    
    // Voeg alle bestaande GET parameters toe (behalve img die we gaan updaten)
    $queryParams = $_GET;
    unset($queryParams['img']);
    if (!empty($queryParams)) {
        $currentUri .= '?' . http_build_query($queryParams);
    }
    
    // Build separate links for Links and Inline modes
    $linksUrl = buildUrlWithImageMode($currentUri, 'links');
    $inlineUrl = buildUrlWithImageMode($currentUri, 'inline');
    
    // Build image mode text with active mode in bold (HTML 2.0 compatible)
    if ($imageMode === 'inline') {
        $linksText = '<a href="' . htmlspecialchars($linksUrl) . '">Links</a>';
        $inlineText = '<a href="' . htmlspecialchars($inlineUrl) . '"><b>Inline</b></a>';
    } else {
        $linksText = '<a href="' . htmlspecialchars($linksUrl) . '"><b>Links</b></a>';
        $inlineText = '<a href="' . htmlspecialchars($inlineUrl) . '">Inline</a>';
    }
    
    $imageModeText = $linksText . ' | ' . $inlineText;
    
    // Haal stats op (met graceful error handling)
    $stats = getStats();
    $visitorsText = 'Visits: ' . formatNumber($stats['unique_visitors']);
    $pageviewsText = 'Pageviews: ' . formatNumber($stats['total_pageviews']);
    
    // HTML 2.0 compatibele navigatie (geen tabellen, geen font tags)
    // Inline layout: alles op één regel met scheidingstekens
    $html = "<p>\n";
    $html .= "<a href=\"" . htmlspecialchars($homeUrl) . "\"><b>" . htmlspecialchars($linkText) . "</b></a> | ";
    $html .= htmlspecialchars($visitorsText) . " | " . htmlspecialchars($pageviewsText) . " | ";
    $html .= "<b>Images:</b> " . $imageModeText . "\n";
    $html .= "</p>\n";
    $html .= "<hr>\n";
    
    return $html;
}

/**
 * Haal content extractor instantie op op basis van configuratie
 * @return \RetroWEB\ContentExtractorInterface Content extractor
 */
function getContentExtractor() {
    $extractorType = defined('CONTENT_EXTRACTOR') ? CONTENT_EXTRACTOR : 'hybrid';
    
    // Zorg dat namespace classes geladen zijn (fallback als autoloader niet werkt)
    if (!class_exists('RetroWEB\ContentExtractorInterface', false)) {
        // Probeer eerst via autoloader (als vendor/autoload.php geladen is)
        if (file_exists(__DIR__ . '/vendor/autoload.php')) {
            // Autoloader zou dit moeten afhandelen, maar als class niet bestaat, laad handmatig
            if (!class_exists('RetroWEB\ContentExtractorInterface')) {
                require_once __DIR__ . '/lib/ContentExtractor.php';
            }
        } else {
            // Geen autoloader, laad handmatig
            require_once __DIR__ . '/lib/ContentExtractor.php';
        }
    }
    
    switch ($extractorType) {
        case 'readability':
            return new \RetroWEB\ReadabilityExtractor();
            
        case 'custom':
            return new \RetroWEB\CustomDOMExtractor();
            
        case 'hybrid':
        default:
            return new \RetroWEB\HybridExtractor();
    }
}

/**
 * Haal SQLite database connectie op (singleton pattern)
 * @return SQLite3|null Database connectie of null bij error
 */
function getStatsDatabase() {
    static $db = null;
    
    if ($db !== null) {
        return $db;
    }
    
    try {
        // Check of SQLite3 beschikbaar is
        if (!class_exists('SQLite3')) {
            error_log('SQLite3 not available - visitor tracking disabled');
            return null;
        }
        
        // Check cache directory
        if (!is_writable(CACHE_DIR)) {
            error_log('Cache directory not writable: ' . CACHE_DIR);
            return null;
        }
        
        $dbPath = CACHE_DIR . '/stats.db';
        $db = new SQLite3($dbPath);
        $db->exec('PRAGMA journal_mode=WAL'); // Betere concurrency
        $db->exec('PRAGMA synchronous=NORMAL'); // Balans tussen safety en speed
        
        // Initialiseer tabellen als ze niet bestaan
        $db->exec("CREATE TABLE IF NOT EXISTS visitor_ips (
            ip_hash TEXT PRIMARY KEY,
            first_seen INTEGER NOT NULL
        )");
        $db->exec("CREATE INDEX IF NOT EXISTS idx_first_seen ON visitor_ips(first_seen)");
        
        $db->exec("CREATE TABLE IF NOT EXISTS stats (
            key TEXT PRIMARY KEY,
            value INTEGER NOT NULL DEFAULT 0
        )");
        
        // Initialiseer stats als ze niet bestaan
        $db->exec("INSERT OR IGNORE INTO stats (key, value) VALUES ('unique_visitors', 0)");
        $db->exec("INSERT OR IGNORE INTO stats (key, value) VALUES ('total_pageviews', 0)");
        
        return $db;
        
    } catch (Exception $e) {
        error_log('Stats database error: ' . $e->getMessage());
        return null;
    }
}

/**
 * Track bezoeker en pageview
 * Hackerproof: gebruikt prepared statements en IP hashing
 */
function trackVisitor() {
    if (!defined('VISITOR_TRACKING_ENABLED') || !VISITOR_TRACKING_ENABLED) {
        return;
    }
    
    try {
        $db = getStatsDatabase();
        if ($db === null) {
            return; // Silent fail - site moet blijven werken
        }
        
        $ip = getClientIp();
        // Valideer IP adres
        if (empty($ip) || $ip === '0.0.0.0') {
            return; // Invalid IP, skip tracking
        }
        
        // Hash IP adres met SHA-256 (hackerproof, geen plaintext opslag)
        $ipHash = hash('sha256', $ip);
        $now = time();
        $window = defined('VISITOR_TRACKING_WINDOW') ? VISITOR_TRACKING_WINDOW : 86400;
        $cutoff = $now - $window;
        
        // Check of bezoeker bestaat (prepared statement voor SQL injection prevention)
        $stmt = $db->prepare('SELECT first_seen FROM visitor_ips WHERE ip_hash = ?');
        $stmt->bindValue(1, $ipHash, SQLITE3_TEXT);
        $result = $stmt->execute();
        $row = $result->fetchArray(SQLITE3_ASSOC);
        
        if ($row === false) {
            // Nieuwe bezoeker
            $stmt = $db->prepare('INSERT INTO visitor_ips (ip_hash, first_seen) VALUES (?, ?)');
            $stmt->bindValue(1, $ipHash, SQLITE3_TEXT);
            $stmt->bindValue(2, $now, SQLITE3_INTEGER);
            $stmt->execute();
            
            // Increment unique visitors
            $stmt = $db->prepare('UPDATE stats SET value = value + 1 WHERE key = ?');
            $stmt->bindValue(1, 'unique_visitors', SQLITE3_TEXT);
            $stmt->execute();
        } elseif ($row['first_seen'] < $cutoff) {
            // Bezoeker bestaat maar is ouder dan window, telt weer als nieuw
            $stmt = $db->prepare('UPDATE visitor_ips SET first_seen = ? WHERE ip_hash = ?');
            $stmt->bindValue(1, $now, SQLITE3_INTEGER);
            $stmt->bindValue(2, $ipHash, SQLITE3_TEXT);
            $stmt->execute();
            
            // Increment unique visitors
            $stmt = $db->prepare('UPDATE stats SET value = value + 1 WHERE key = ?');
            $stmt->bindValue(1, 'unique_visitors', SQLITE3_TEXT);
            $stmt->execute();
        }
        // Anders: bezoeker bestaat en is binnen window, geen actie
        
        // Altijd pageview incrementen
        $stmt = $db->prepare('UPDATE stats SET value = value + 1 WHERE key = ?');
        $stmt->bindValue(1, 'total_pageviews', SQLITE3_TEXT);
        $stmt->execute();
        
    } catch (Exception $e) {
        error_log('trackVisitor error: ' . $e->getMessage());
        // Silent fail - site moet blijven werken
    }
}

/**
 * Haal stats op met caching
 * @return array ['unique_visitors' => int, 'total_pageviews' => int]
 */
function getStats() {
    try {
        $db = getStatsDatabase();
        if ($db === null) {
            return ['unique_visitors' => 0, 'total_pageviews' => 0];
        }
        
        // Cache stats voor X seconden om database queries te verminderen
        static $cachedStats = null;
        static $cacheTime = 0;
        $cacheTtl = defined('STATS_CACHE_TTL') ? STATS_CACHE_TTL : 5;
        
        if ($cachedStats !== null && (time() - $cacheTime) < $cacheTtl) {
            return $cachedStats;
        }
        
        $stats = [];
        $result = $db->query('SELECT key, value FROM stats');
        while ($row = $result->fetchArray(SQLITE3_ASSOC)) {
            $stats[$row['key']] = (int)$row['value'];
        }
        
        $cachedStats = [
            'unique_visitors' => $stats['unique_visitors'] ?? 0,
            'total_pageviews' => $stats['total_pageviews'] ?? 0
        ];
        $cacheTime = time();
        
        return $cachedStats;
        
    } catch (Exception $e) {
        error_log('getStats error: ' . $e->getMessage());
        return ['unique_visitors' => 0, 'total_pageviews' => 0];
    }
}

/**
 * Format groot getal met komma's (bijv. 1234 -> 1,234)
 * @param int $number
 * @return string
 */
function formatNumber($number) {
    return number_format($number, 0, '.', ',');
}
