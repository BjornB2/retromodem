<?php
/**
 * RetroWEB - Configuratie
 */

require_once __DIR__ . '/lib/ConfigLoader.php';
require_once __DIR__ . '/lib/DeviceProfiles.php';
require_once __DIR__ . '/lib/UserSettings.php';

$retroWebConfig = \RetroWEB\ConfigLoader::load(__DIR__);

function defineRetroWebConfig(array $config): void {
    $constants = [
        'public_host' => 'PUBLIC_HOST',
        'cache_dir' => 'CACHE_DIR',
        'cache_ttl' => 'CACHE_TTL',
        'cache_ttl_failed' => 'CACHE_TTL_FAILED',
        'cache_version' => 'CACHE_VERSION',
        'render_version' => 'RENDER_VERSION',
        'image_cache_ttl' => 'IMAGE_CACHE_TTL',
        'image_cache_revalidate' => 'IMAGE_CACHE_REVALIDATE',
        'image_cache_max_files' => 'IMAGE_CACHE_MAX_FILES',
        'image_cache_max_bytes' => 'IMAGE_CACHE_MAX_BYTES',
        'max_download_size' => 'MAX_DOWNLOAD_SIZE',
        'max_image_width' => 'MAX_IMAGE_WIDTH',
        'max_image_height' => 'MAX_IMAGE_HEIGHT',
        'min_image_size' => 'MIN_IMAGE_SIZE',
        'jpg_quality' => 'JPG_QUALITY',
        'gif_palette_colors' => 'GIF_PALETTE_COLORS',
        'gif_use_dithering' => 'GIF_USE_DITHERING',
        'user_agent' => 'USER_AGENT',
        'content_extractor' => 'CONTENT_EXTRACTOR',
        'app_env' => 'APP_ENV',
        'rate_limit_enabled' => 'RATE_LIMIT_ENABLED',
        'rate_limit_requests' => 'RATE_LIMIT_REQUESTS',
        'rate_limit_window' => 'RATE_LIMIT_WINDOW',
        'max_url_length' => 'MAX_URL_LENGTH',
        'max_image_processing_size' => 'MAX_IMAGE_PROCESSING_SIZE',
        'image_processing_timeout' => 'IMAGE_PROCESSING_TIMEOUT',
        'max_search_query_length' => 'MAX_SEARCH_QUERY_LENGTH',
        'max_redirect_depth' => 'MAX_REDIRECT_DEPTH',
        'max_request_size' => 'MAX_REQUEST_SIZE',
        'request_timeout' => 'REQUEST_TIMEOUT',
        'visitor_tracking_enabled' => 'VISITOR_TRACKING_ENABLED',
        'visitor_tracking_window' => 'VISITOR_TRACKING_WINDOW',
        'stats_cache_ttl' => 'STATS_CACHE_TTL',
        'settings_session_ttl' => 'SETTINGS_SESSION_TTL',
        'forward_proxy_monthly_bytes' => 'FORWARD_PROXY_MONTHLY_BYTES',
        'forward_proxy_daily_bytes' => 'FORWARD_PROXY_DAILY_BYTES',
        'forward_proxy_ip_daily_bytes' => 'FORWARD_PROXY_IP_DAILY_BYTES',
    ];

    foreach ($constants as $key => $constant) {
        if (!array_key_exists($key, $config)) {
            throw new RuntimeException('Missing configuration key: ' . $key);
        }
        if (!defined($constant)) {
            define($constant, $config[$key]);
        }
    }
}

defineRetroWebConfig($retroWebConfig);
unset($retroWebConfig);

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
    $scriptDirectory = rtrim(dirname($_SERVER['SCRIPT_NAME']), '/');
    define('BASE_PATH', ($scriptDirectory === '' || $scriptDirectory === '.') ? '/' : $scriptDirectory);
} else {
    // Fallback als SCRIPT_NAME niet beschikbaar is
    define('BASE_PATH', '/');
}

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
 * Return response headers from the most recent HTTP stream request.
 *
 * PHP versions before http_get_last_response_headers() cannot expose these
 * without referencing the deprecated magic $http_response_header variable.
 * In that case callers safely continue without optional response metadata.
 */
function getLastHttpResponseHeaders(array $requestScope = []): array {
    if (!function_exists('http_get_last_response_headers')) {
        $headers = $requestScope['http_response_header'] ?? [];
        return is_array($headers) ? $headers : [];
    }

    $headers = http_get_last_response_headers();
    return is_array($headers) ? $headers : [];
}

/**
 * Retourneert volledige base URL met protocol en host
 * Voor oude browsers zoals MacWeb 2.0 die absolute URLs nodig hebben
 * @return string Volledige base URL (bijv. http://retroweb.heirman.nl)
 */
function getBaseUrl() {
    // Hardcoded base URL voor deze installatie
    $host = PUBLIC_HOST;
    
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

/** Connection details for RetroModem's local and optional public proxy routes. */
function renderForwardProxyNotice(): string {
    return "<h2>Use RetroWEB as a browser proxy</h2>\n"
        . "<p><b>Local proxy:</b> <code>192.168.77.1</code>, port <code>8080</code>.</p>\n"
        . "<p><b>Online proxy:</b> <code>retroweb.bjrno.com</code>, port <code>8081</code>.</p>\n"
        . "<p>Configure exactly one of these as an HTTP proxy in your browser. The online route requires an internet connection. Do not use either proxy for passwords, payments or other sensitive information.</p>\n";
}

function getUserSettings(): array {
    static $settings = null;
    if ($settings === null) {
        $settings = \RetroWEB\UserSettings::resolve(
            array_replace($_GET, $_POST),
            $_COOKIE,
            getClientUserAgent(),
            getServerSettingsSession()
        );
    }
    return $settings;
}

function getClientUserAgent(): string {
    foreach (['HTTP_X_RETROMODEM_USER_AGENT', 'HTTP_X_ORIGINAL_USER_AGENT', 'HTTP_USER_AGENT'] as $key) {
        if (isset($_SERVER[$key]) && is_string($_SERVER[$key]) && trim($_SERVER[$key]) !== '') {
            return substr(trim($_SERVER[$key]), 0, 1024);
        }
    }
    return '';
}

/** A short-lived, anonymous key for restoring settings in browsers without cookies. */
function settingsSessionFingerprint(): ?string {
    $forwardClient = trustedForwardProxyClientId();
    if ($forwardClient !== null) return 'forward:' . $forwardClient;
    $ip = getClientIp();
    $agent = getClientUserAgent();
    if ($ip === '' && $agent === '') return null;

    $keyFile = CACHE_DIR . '/settings-session.key';
    $secret = is_file($keyFile) ? file_get_contents($keyFile) : false;
    if (!is_string($secret) || strlen($secret) < 32) {
        try {
            $secret = random_bytes(32);
        } catch (Throwable $e) {
            error_log('Unable to create settings session key: ' . $e->getMessage());
            return null;
        }
        if (file_put_contents($keyFile, $secret, LOCK_EX) === false) return null;
        @chmod($keyFile, 0600);
    }
    return hash_hmac('sha256', $ip . "\n" . $agent, $secret);
}

/** Trust the opaque forward-proxy identity only across the local loopback hop. */
function trustedForwardProxyClientId(): ?string {
    $remote = $_SERVER['REMOTE_ADDR'] ?? '';
    $value = $_SERVER['HTTP_X_RETROWEB_CLIENT_ID'] ?? '';
    if (!in_array($remote, ['127.0.0.1', '::1'], true) || !is_string($value)
        || !preg_match('/^[a-f0-9]{64}$/D', $value)) return null;
    return strtolower($value);
}

function getServerSettingsSession(): array {
    $fingerprint = settingsSessionFingerprint();
    $db = $fingerprint !== null ? getStatsDatabase() : null;
    if (!$db) return [];
    try {
        $statement = $db->prepare('SELECT settings FROM settings_sessions WHERE fingerprint = :fingerprint AND updated_at >= :minimum');
        $statement->bindValue(':fingerprint', $fingerprint, SQLITE3_TEXT);
        $statement->bindValue(':minimum', time() - SETTINGS_SESSION_TTL, SQLITE3_INTEGER);
        $row = $statement->execute()->fetchArray(SQLITE3_ASSOC);
        if (!$row) return [];
        $settings = json_decode($row['settings'], true);
        return is_array($settings) ? $settings : [];
    } catch (Throwable $e) {
        error_log('Settings session read failed: ' . $e->getMessage());
        return [];
    }
}

function rememberUserSettings(array $settings): void {
    $fingerprint = settingsSessionFingerprint();
    $db = $fingerprint !== null ? getStatsDatabase() : null;
    if (!$db) return;
    $stored = array_replace(\RetroWEB\UserSettings::query($settings), [
        '_resolved' => \RetroWEB\DeviceProfiles::storageGeneration($settings['resolved_profile']),
        '_profile_bindings' => '3',
    ]);
    try {
        $statement = $db->prepare('INSERT INTO settings_sessions (fingerprint, settings, updated_at) VALUES (:fingerprint, :settings, :updated_at)
            ON CONFLICT(fingerprint) DO UPDATE SET settings = excluded.settings, updated_at = excluded.updated_at');
        $statement->bindValue(':fingerprint', $fingerprint, SQLITE3_TEXT);
        $statement->bindValue(':settings', json_encode($stored), SQLITE3_TEXT);
        $statement->bindValue(':updated_at', time(), SQLITE3_INTEGER);
        $statement->execute();
        $db->exec('DELETE FROM settings_sessions WHERE updated_at < ' . (time() - SETTINGS_SESSION_TTL));
    } catch (Throwable $e) {
        error_log('Settings session write failed: ' . $e->getMessage());
    }
}

/** MacWeb 2.0 sends literal "&amp;" text from URL attributes. */
function prepareLegacyBrowserHtml(string $html, ?array $settings = null): string {
    $settings ??= getUserSettings();
    if (($settings['resolved_profile'] ?? '') !== 'macweb') return $html;
    return preg_replace_callback('/\b(href|src|action)=("|\')(.*?)\2/is', static function ($match) {
        return $match[1] . '=' . $match[2] . str_replace('&amp;', '&', $match[3]) . $match[2];
    }, $html);
}

function buildRetroWebUrl(string $script, array $parameters = []): string {
    $url = rtrim(getBaseUrl(), '/') . '/' . ltrim($script, '/');
    return $parameters ? $url . '?' . http_build_query($parameters) : $url;
}

/** Apply newly saved settings to a safe internal return URL. */
function settingsReturnUrl($candidate, array $settings): ?string {
    if (!is_string($candidate) || $candidate === '' || preg_match('/[\r\n]/', $candidate)) return null;
    $return = parse_url($candidate);
    $base = parse_url(getBaseUrl());
    if (!$return || !$base) return null;
    if (strcasecmp($return['scheme'] ?? '', $base['scheme'] ?? '') !== 0
        || strcasecmp($return['host'] ?? '', $base['host'] ?? '') !== 0
        || ($return['port'] ?? null) !== ($base['port'] ?? null)) return null;

    $basePath = rtrim(getBasePath(), '/');
    $allowedPaths = [($basePath ?: '') . '/index.php', ($basePath ?: '') . '/proxy.php'];
    if (!in_array($return['path'] ?? '', $allowedPaths, true)) return null;
    parse_str($return['query'] ?? '', $parameters);
    $parameters = array_replace($parameters, \RetroWEB\UserSettings::query($settings));
    return buildRetroWebUrl(basename($return['path']), $parameters);
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
    
    $addresses = resolvePublicTargetAddresses((string)$url);
    if (!$addresses) return true;
    $ip = $addresses[0];
    
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

/** Resolve every A/AAAA address and reject the complete target if any is not public. */
function resolvePublicTargetAddresses(string $url): array {
    $host = strtolower(trim((string)parse_url($url, PHP_URL_HOST), '[]'));
    if ($host === '') return [];
    if (filter_var($host, FILTER_VALIDATE_IP)) {
        $addresses = [$host];
    } else {
        $addresses = [];
        $records = @dns_get_record($host, DNS_A | DNS_AAAA);
        if (!is_array($records)) return [];
        foreach ($records as $record) {
            if (!empty($record['ip'])) $addresses[] = $record['ip'];
            if (!empty($record['ipv6'])) $addresses[] = $record['ipv6'];
        }
    }
    $addresses = array_values(array_unique($addresses));
    if (!$addresses) return [];
    foreach ($addresses as $address) {
        if (!filter_var($address, FILTER_VALIDATE_IP, FILTER_FLAG_NO_PRIV_RANGE | FILTER_FLAG_NO_RES_RANGE)) return [];
    }
    return $addresses;
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
        error_reporting(E_ALL);
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
        // Respect @ suppression and the active error_reporting mask.
        if ((error_reporting() & $errno) === 0) {
            return false;
        }

        $errorMsg = "PHP Error [$errno]: $errstr in $errfile on line $errline";
        writeRetroWebLog($errorMsg);
        return true; // Prevent PHP from writing the same error a second time.
    });
    
    // Set exception handler
    set_exception_handler(function($exception) {
        $errorMsg = "PHP Exception: " . $exception->getMessage() . "\n";
        $errorMsg .= "File: " . $exception->getFile() . "\n";
        $errorMsg .= "Line: " . $exception->getLine() . "\n";
        $errorMsg .= $exception->getTraceAsString() . "\n";
        writeRetroWebLog($errorMsg);
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
            writeRetroWebLog($errorMsg);
        }
    });
}

/**
 * Remove binary payloads and cap application log entries.
 */
function sanitizeLogMessage(string $message, int $maximumBytes = 4096): string {
    $message = preg_replace(
        '#data:[a-z0-9.+-]+/[a-z0-9.+-]+;base64,[a-z0-9+/=]+#i',
        '[data URI omitted]',
        $message
    );
    $message = preg_replace('/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/', '', (string)$message);
    if (strlen($message) > $maximumBytes) {
        $message = substr($message, 0, max(0, $maximumBytes - 24)) . '...[entry truncated]';
    }
    return rtrim($message);
}

function writeRetroWebLog(string $message): void {
    $line = '[' . gmdate('d-M-Y H:i:s') . " UTC] " . sanitizeLogMessage($message) . "\n";
    error_log($line, 3, __DIR__ . '/error.log');
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
        410 => 'Gone',
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

/** Prevent browsers and intermediary proxies from retaining generated HTML. */
function setHtmlNoCacheHeaders(): void {
    if (headers_sent()) return;
    header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
    header('Pragma: no-cache');
    header('Expires: Thu, 01 Jan 1970 00:00:00 GMT');
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
    return getUserSettings()['image_mode'];
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
    $html = preg_replace('/<del\b[^>]*>/i', '<strike>', $html);
    $html = preg_replace('/<\/del>/i', '</strike>', $html);
    $html = preg_replace('/<ins\b[^>]*>/i', '<u>', $html);
    $html = preg_replace('/<\/ins>/i', '</u>', $html);
    $html = preg_replace('/<mark\b[^>]*>/i', '<b>', $html);
    $html = preg_replace('/<\/mark>/i', '</b>', $html);
    
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
 * Hide only a clear one-pixel tracker, never arbitrary small images.
 * @param string $imgTag Volledige img tag HTML
 * @param string $url Image URL (voor pattern matching)
 * @param string $originalHtml Originele HTML (voor CSS parsing)
 * @return bool True als image verborgen moet worden
 */
function shouldHideImage($imgTag, $url = '', $originalHtml = '', $isLinked = false) {
    $dimensions = extractImageDimensions($imgTag, $originalHtml);
    // Small does not mean decorative: retain buttons, diagrams and avatars.
    // Suppress only an unlinked, unlabelled, explicitly one-pixel tracker.
    preg_match('/\balt\s*=\s*["\']([^"\']*)["\']/i', $imgTag, $alt);
    $label = trim(html_entity_decode($alt[1] ?? '', ENT_QUOTES, 'ISO-8859-1'));
    return !$isLinked && $label === '' && $dimensions['width'] === 1 && $dimensions['height'] === 1;
}

/** Canonical inline images, retaining location and safe display hints.
 * The paginator derives image-link variants later from this shared content.
 */
function mergeImageHints(array $previous, array $incoming): array {
    foreach (['width', 'height', 'alt'] as $key) {
        if (!empty($previous['ambiguous_' . $key]) || ($previous[$key] ?? null) !== ($incoming[$key] ?? null)) {
            $incoming[$key] = null;
            $incoming['ambiguous_' . $key] = true;
        }
    }
    return $incoming;
}

function renderCanonicalImages(string $content, string $baseUrl, string $targetUrl,
                               string $originalHtml = '', array $imageMap = [], array $imageDimensions = []): string {
    $number = 0;
    $settings=getUserSettings();
    return preg_replace_callback('/<img\b[^>]*>/i', function ($matches) use (&$number, $content, $baseUrl, $targetUrl, $originalHtml, $imageMap, $imageDimensions, $settings) {
        $tag = $matches[0][0];
        $offset = $matches[0][1];
        if (!preg_match('/\bsrc\s*=\s*["\']([^"\']+)["\']/i', $tag, $src)) return '';
        $rawUrl = html_entity_decode($src[1], ENT_QUOTES, 'UTF-8');
        $url = $imageMap[$rawUrl] ?? normalizeImageUrl($rawUrl, $targetUrl);
        if (!is_string($url) || !preg_match('/^https?:\/\//i', $url)) return '';
        // Count anchors before this exact occurrence, not the first identical img.
        $before = substr($content, 0, $offset);
        $isLinked = preg_match_all('/<a\b[^>]*>/i', $before) > preg_match_all('/<\/a\s*>/i', $before);
        if (shouldHideImage($tag, $url, $originalHtml, $isLinked)) return '';
        $dimensions = extractImageDimensions($tag, $originalHtml);
        foreach (['width', 'height'] as $axis) {
            if ($dimensions[$axis] === null && isset($imageDimensions[$url][$axis])) {
                $dimensions[$axis] = $imageDimensions[$url][$axis];
            }
            if ($dimensions[$axis] !== null && $dimensions[$axis] <= 0) $dimensions[$axis] = null;
        }
        $width = $dimensions['width'];
        $height = $dimensions['height'];
        if ($width !== null && $height !== null) {
            $ratio = min(1, max(1,$settings['image_width']) / $width, max(1,$settings['image_height']) / $height);
            $width = max(1, (int)floor($width * $ratio));
            $height = max(1, (int)floor($height * $ratio));
        } else {
            if ($width !== null) $width = min($width, $settings['image_width']);
            if ($height !== null) $height = min($height, $settings['image_height']);
        }
        $parameters = \RetroWEB\UserSettings::query($settings, ['url' => $url]);
        if ($width !== null) $parameters['w'] = $width;
        if ($height !== null) $parameters['h'] = $height;
        $asset = rtrim($baseUrl, '/') . '/image_cruncher.php?' . http_build_query($parameters);
        preg_match('/\balt\s*=\s*["\']([^"\']*)["\']/i', $tag, $altMatch);
        $alt = html_entity_decode($altMatch[1] ?? $imageDimensions[$url]['alt'] ?? '', ENT_QUOTES, 'UTF-8');
        $number++;
        $label = (retromodemNavigationLanguage() === 'nl' ? 'Afbeelding ' : 'Image ') . $number . ($alt !== '' ? ': ' . $alt : '');
        $escape = fn($value) => mb_encode_numericentity(htmlspecialchars((string)$value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8', false), [128, 0x10ffff, 0, 0x1fffff], 'UTF-8');
        $image = '<img src="' . $escape($asset) . '" alt="' . $escape($alt) . '" data-rm-link-label="' . $escape($label) . '"';
        $image .= ' data-rm-pixels="' . (($width ?? $settings['image_width']) * ($height ?? $settings['image_height'])) . '"';
        // Preserve the source site's intended display size, capped
        // proportionally by RetroWEB. This never enlarges beyond the hint.
        if ($width !== null) $image .= ' width="' . $width . '"';
        if ($height !== null) $image .= ' height="' . $height . '"';
        // Do not wrap in a paragraph inside an existing functional link.
        $after = substr($content, $offset + strlen($tag), 32);
        $lineBreak = preg_match('/^\s*<br\b/i', $after) ? '' : '<br>';
        return $image . '>' . $lineBreak;
    }, $content, -1, $count, PREG_OFFSET_CAPTURE);
}

/** Return dimensions that preserve aspect ratio and can never upscale. */
function calculateDownscaledDimensions(int $actualWidth, int $actualHeight, int $maxWidth, int $maxHeight,
                                       ?int $hintWidth = null, ?int $hintHeight = null): array {
    if ($actualWidth < 1 || $actualHeight < 1) return [1, 1];
    $limitWidth = max(1, $maxWidth);
    $limitHeight = max(1, $maxHeight);
    if ($hintWidth !== null && $hintWidth > 0) $limitWidth = min($limitWidth, $hintWidth);
    if ($hintHeight !== null && $hintHeight > 0) $limitHeight = min($limitHeight, $hintHeight);
    $ratio = min(1.0, $limitWidth / $actualWidth, $limitHeight / $actualHeight);
    return [max(1, (int)floor($actualWidth * $ratio)), max(1, (int)floor($actualHeight * $ratio))];
}

/**
 * Maak stream context voor HTTP requests
 * @param string $method HTTP method (GET, HEAD, etc.)
 * @return resource Stream context
 */
function createStreamContext($method = 'GET', ?string $body = null, array $extraHeaders = []) {
    $timeout = defined('REQUEST_TIMEOUT') ? REQUEST_TIMEOUT : 30;
    $maxRedirects = defined('MAX_REDIRECT_DEPTH') ? MAX_REDIRECT_DEPTH : 5;
    $headers = "User-Agent: " . USER_AGENT . "\r\n";
    if ($body !== null) {
        $headers .= "Content-Type: application/x-www-form-urlencoded\r\n";
        $headers .= "Content-Length: " . strlen($body) . "\r\n";
    }
    foreach ($extraHeaders as $name => $value) {
        if (preg_match('/^[A-Za-z0-9-]+$/', (string)$name) && is_string($value) && !preg_match('/[\r\n]/', $value)) {
            $headers .= $name . ': ' . $value . "\r\n";
        }
    }
    
    return stream_context_create([
        'http' => [
            'method' => $method,
            'header' => $headers,
            'content' => $body ?? '',
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
function retromodemNavigationLanguage(): string {
    $language = $_GET['lang'] ?? getenv('RETROMODEM_LANGUAGE');
    return is_string($language) && $language === 'nl' ? 'nl' : 'en';
}

function renderNavigation($imageMode = null, ?string $reloadUrl = null) {
    $s=getUserSettings();
    $label=htmlspecialchars($s['profile_label'],ENT_QUOTES,'ISO-8859-1').($s['automatic']?' (auto)':'');
    $home=htmlspecialchars(buildRetroWebUrl('index.php',\RetroWEB\UserSettings::query($s)),ENT_QUOTES,'ISO-8859-1');
    $settingsParameters=\RetroWEB\UserSettings::query($s);
    if (settingsReturnUrl($reloadUrl, $s) !== null) $settingsParameters['return']=$reloadUrl;
    $settings=htmlspecialchars(buildRetroWebUrl('settings.php',$settingsParameters),ENT_QUOTES,'ISO-8859-1');
    $reload='';
    if (is_string($reloadUrl) && preg_match('/^https?:\/\//i',$reloadUrl)) {
        $reloadLabel='Reload';
        $reload=' | <a href="'.htmlspecialchars($reloadUrl,ENT_QUOTES,'ISO-8859-1').'">'.$reloadLabel.'</a>';
    }
    return '<p><small><a href="'.$home.'"><b>RetroWEB</b></a> | Profile: '.$label.' | Images: '.$s['image_width'].'x'.$s['image_height'].' | <a href="'.$settings.'">Settings</a>'.$reload.'</small></p><hr>';
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
        $db->enableExceptions(true);
        $db->busyTimeout(5000);
        $db->exec('PRAGMA busy_timeout=5000');
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
        foreach (['processed_pages','processed_images','processing_success','processing_error',
                  'processing_under_500ms','processing_under_2s','processing_over_2s'] as $key) {
            $db->exec("INSERT OR IGNORE INTO stats (key, value) VALUES ('" . $key . "', 0)");
        }
        $db->exec("CREATE TABLE IF NOT EXISTS profile_stats (
            profile TEXT PRIMARY KEY,
            value INTEGER NOT NULL DEFAULT 0
        )");
        $db->exec("CREATE TABLE IF NOT EXISTS settings_sessions (
            fingerprint TEXT PRIMARY KEY,
            settings TEXT NOT NULL,
            updated_at INTEGER NOT NULL
        )");
        $db->exec("CREATE INDEX IF NOT EXISTS idx_settings_sessions_updated ON settings_sessions(updated_at)");
        
        return $db;
        
    } catch (Exception $e) {
        $db = null;
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
        
        $db->exec('BEGIN IMMEDIATE');

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

        $db->exec('COMMIT');
        
    } catch (Exception $e) {
        if (isset($db) && $db instanceof SQLite3) {
            try {
                $db->exec('ROLLBACK');
            } catch (Exception $ignored) {
                // No active transaction or the connection is unavailable.
            }
        }
        // Contention is expected under bursts; dropping one statistic is safer
        // than delaying or failing the requested page.
        if (stripos($e->getMessage(), 'locked') === false) {
            writeRetroWebLog('trackVisitor error: ' . $e->getMessage());
        }
        // Silent fail - site moet blijven werken
    }
}

/**
 * Haal stats op met caching
 * @return array ['unique_visitors' => int, 'total_pageviews' => int]
 */
function getStats(bool $fresh = false) {
    try {
        $db = getStatsDatabase();
        if ($db === null) {
            return ['unique_visitors' => 0, 'total_pageviews' => 0];
        }
        
        // Cache stats voor X seconden om database queries te verminderen
        static $cachedStats = null;
        static $cacheTime = 0;
        $cacheTtl = defined('STATS_CACHE_TTL') ? STATS_CACHE_TTL : 5;
        
        if (!$fresh && $cachedStats !== null && (time() - $cacheTime) < $cacheTtl) {
            return $cachedStats;
        }
        
        $stats = [];
        $result = $db->query('SELECT key, value FROM stats');
        while ($row = $result->fetchArray(SQLITE3_ASSOC)) {
            $stats[$row['key']] = (int)$row['value'];
        }
        
        $cachedStats = [];
        foreach (['unique_visitors','total_pageviews','processed_pages','processed_images','processing_success',
                  'processing_error','processing_under_500ms','processing_under_2s','processing_over_2s'] as $key) {
            $cachedStats[$key] = $stats[$key] ?? 0;
        }
        $cacheTime = time();
        
        return $cachedStats;
        
    } catch (Exception $e) {
        error_log('getStats error: ' . $e->getMessage());
        return ['unique_visitors' => 0, 'total_pageviews' => 0];
    }
}

/** Public, aggregate-only counters. Never returns visitor identifiers. */
function getPublicStats(): array {
    $stats = getStats(true);
    $stats['active_visitors'] = 0;
    $stats['window_seconds'] = defined('VISITOR_TRACKING_WINDOW') ? VISITOR_TRACKING_WINDOW : 3600;
    try {
        $db = getStatsDatabase();
        if ($db !== null) {
            $stmt = $db->prepare('SELECT COUNT(*) AS count FROM visitor_ips WHERE first_seen >= ?');
            $stmt->bindValue(1, time() - $stats['window_seconds'], SQLITE3_INTEGER);
            $result = $stmt->execute();
            $row = $result->fetchArray(SQLITE3_ASSOC);
            $stats['active_visitors'] = max(0, (int)($row['count'] ?? 0));
            $stats['profiles'] = [];
            $profiles = $db->query('SELECT profile, value FROM profile_stats ORDER BY value DESC, profile ASC LIMIT 10');
            while ($profile = $profiles->fetchArray(SQLITE3_ASSOC)) {
                $stats['profiles'][(string)$profile['profile']] = max(0, (int)$profile['value']);
            }
        }
    } catch (Exception $e) {
        if (stripos($e->getMessage(), 'locked') === false) writeRetroWebLog('getPublicStats error: ' . $e->getMessage());
    }
    return $stats;
}

function recordAggregateProcessing(string $kind, string $profile, bool $success, float $seconds): void {
    if (!in_array($kind, ['page','image'], true)) return;
    if (!preg_match('/^[a-z0-9_-]{1,40}$/', $profile)) $profile = 'unknown';
    $bucket = $seconds < 0.5 ? 'processing_under_500ms' : ($seconds < 2.0 ? 'processing_under_2s' : 'processing_over_2s');
    try {
        $db = getStatsDatabase();
        if ($db === null) return;
        $db->exec('BEGIN IMMEDIATE');
        foreach ([$kind === 'page' ? 'processed_pages' : 'processed_images', $success ? 'processing_success' : 'processing_error', $bucket] as $key) {
            $stmt = $db->prepare('UPDATE stats SET value = value + 1 WHERE key = ?');
            $stmt->bindValue(1, $key, SQLITE3_TEXT);
            $stmt->execute();
        }
        $stmt = $db->prepare('INSERT INTO profile_stats(profile,value) VALUES(?,1) ON CONFLICT(profile) DO UPDATE SET value=value+1');
        $stmt->bindValue(1, $profile, SQLITE3_TEXT);
        $stmt->execute();
        $db->exec('COMMIT');
    } catch (Exception $e) {
        if (isset($db) && $db instanceof SQLite3) try { $db->exec('ROLLBACK'); } catch (Exception $ignored) {}
        if (stripos($e->getMessage(), 'locked') === false) writeRetroWebLog('recordAggregateProcessing error: ' . $e->getMessage());
    }
}

function registerAggregateProcessing(string $kind, string $profile): void {
    $started = microtime(true);
    register_shutdown_function(static function () use ($kind, $profile, $started): void {
        $status = http_response_code();
        recordAggregateProcessing($kind, $profile, $status >= 200 && $status < 400, microtime(true) - $started);
    });
}

/**
 * Format groot getal met komma's (bijv. 1234 -> 1,234)
 * @param int $number
 * @return string
 */
function formatNumber($number) {
    return number_format($number, 0, '.', ',');
}
