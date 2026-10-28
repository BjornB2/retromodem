<?php
/** Transport for the embedded modem; the RetroWEB extractor remains unchanged. */
function fetchModemUpstreamOnce($url) {
    $cookieDir = sys_get_temp_dir() . '/retromodem-cookies';
    if (!is_dir($cookieDir)) {
        mkdir($cookieDir, 0700, true);
    }
    // One modem session, shared across redirects; libcurl enforces cookie domains.
    $jar = $cookieDir . '/session.txt';
    $result = null;
    $deadline = microtime(true) + 25;
    for ($redirect = 0; $redirect < 8; $redirect++) {
        if (isInternalUrl($url)) {
            throw new RuntimeException('Redirect naar een intern adres geweigerd.', 403);
        }
        $remaining = (int)(($deadline - microtime(true)) * 1000);
        if ($remaining <= 0) throw new RuntimeException('Website reageert niet op tijd.', 28);
        $headers = [];
        $curl = curl_init($url);
        curl_setopt_array($curl, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_FOLLOWLOCATION => false,
            CURLOPT_CONNECTTIMEOUT_MS => min(8000, $remaining),
            CURLOPT_TIMEOUT_MS => $remaining,
            CURLOPT_PROTOCOLS => CURLPROTO_HTTP | CURLPROTO_HTTPS,
            CURLOPT_USERAGENT => USER_AGENT,
            CURLOPT_HTTPHEADER => ['Accept: text/html,application/xhtml+xml,image/*;q=0.8,*/*;q=0.5', 'Accept-Language: nl-NL,nl;q=0.9,en;q=0.7'],
            CURLOPT_ENCODING => '',
            CURLOPT_COOKIEFILE => $jar,
            CURLOPT_COOKIEJAR => $jar,
            CURLOPT_HEADERFUNCTION => function ($handle, $line) use (&$headers) {
                $parts = explode(':', $line, 2);
                if (count($parts) === 2) $headers[strtolower(trim($parts[0]))] = trim($parts[1]);
                return strlen($line);
            },
        ]);
        $body = curl_exec($curl);
        $status = curl_getinfo($curl, CURLINFO_HTTP_CODE);
        $type = curl_getinfo($curl, CURLINFO_CONTENT_TYPE) ?: 'text/html';
        $error = curl_error($curl);
        $errorCode = curl_errno($curl);
        curl_setopt($curl, CURLOPT_COOKIELIST, 'FLUSH');
        curl_close($curl);
        if ($body === false) throw new RuntimeException('Website reageert niet: ' . $error, $errorCode);
        if (strlen($body) > MAX_DOWNLOAD_SIZE) throw new RuntimeException('Pagina is te groot.', 413);
        $result = ['url' => $url, 'body' => $body, 'status' => $status, 'type' => strtolower(explode(';', $type)[0]), 'headers' => $headers];
        if (in_array($status, [301, 302, 303, 307, 308]) && isset($headers['location'])) {
            $url = normalizeImageUrl($headers['location'], $url);
            continue;
        }
        return $result;
    }
    throw new RuntimeException('Te veel doorverwijzingen.', 508);
}

function modemRetrySeconds($value, $now): int {
    if (is_string($value) && ctype_digit($value)) $seconds = (int)$value;
    else $seconds = is_string($value) && strtotime($value) !== false ? strtotime($value) - $now : 60;
    return max(1, min(300, $seconds));
}

function modemOriginalSource($url): ?string {
    $parts = parse_url($url);
    if (!in_array(strtolower($parts['host'] ?? ''), ['wikiwand.com', 'www.wikiwand.com'], true)) return null;
    if (!preg_match('~^/([a-z]{2,12}(?:-[a-z]{2,12})?)/(?:articles/)?(.+)$~D', $parts['path'] ?? '', $match)) return null;
    return 'https://' . $match[1] . '.wikipedia.org/wiki/' . str_replace('%2F', '/', rawurlencode(rawurldecode($match[2])))
        . (isset($parts['fragment']) ? '#' . $parts['fragment'] : '');
}

function fetchModemUpstream($url, bool $allowHttpFallback = false, ?callable $transport = null,
                            ?string $backoffDirectory = null, ?callable $clock = null) {
    $transport ??= 'fetchModemUpstreamOnce';
    $clock ??= fn() => time();
    $now = $clock();
    $backoffDirectory ??= sys_get_temp_dir() . '/retromodem-upstream-backoff';
    $key = hash('sha256', strtolower(parse_url($url, PHP_URL_HOST) ?: ''));
    $path = $backoffDirectory . '/' . $key . '.json';
    $cached = is_file($path) && !is_link($path) ? json_decode(file_get_contents($path), true) : null;
    if (is_array($cached) && is_int($cached['until'] ?? null) && $cached['until'] > $now) {
        return ['url' => $url, 'body' => '', 'type' => 'text/html', 'status' => 429,
                'retry_seconds' => min(300, $cached['until'] - $now), 'backoff' => true];
    }
    $note = '';
    try {
        try {
            $result = $transport($url);
        } catch (RuntimeException $error) {
            // Only an explicitly HTTP browser request may recover from an
            // unsupported TLS handshake. Never ignore certificate failures.
            if (!$allowHttpFallback || $error->getCode() !== 35 || parse_url($url, PHP_URL_SCHEME) !== 'https') throw $error;
            $plain = 'http://' . substr($url, strlen('https://'));
            $result = $transport($plain);
            $note = 'http-fallback';
        }
    } catch (RuntimeException $error) {
        $failure = match ($error->getCode()) {
            28 => 'timeout', 35, 60, 77 => 'tls', 6 => 'dns', 403 => 'blocked', 413 => 'size', 508 => 'redirects', default => 'connection'
        };
        error_log('RetroModem source failure: ' . (parse_url($url, PHP_URL_HOST) ?: '') . ' ' . $failure);
        return ['url' => $url, 'body' => '', 'type' => 'text/html', 'status' => 0, 'failure' => $failure];
    }
    if ($note !== '') $result['transport_note'] = $note;
    $original = modemOriginalSource($url);
    if ($original !== null && modemUpstreamProblem($result) !== null) {
        try {
            $alternative = $transport($original);
            if (modemUpstreamProblem($alternative) === null) {
                $alternative['transport_note'] = 'original-wikipedia';
                return $alternative;
            }
        } catch (RuntimeException $ignored) {
            // Keep the actual source error if the original is unavailable too.
        }
    }
    if ($result['status'] === 429) {
        $seconds = modemRetrySeconds($result['headers']['retry-after'] ?? null, $now);
        $result['retry_seconds'] = $seconds;
        if (!is_dir($backoffDirectory)) @mkdir($backoffDirectory, 0700, true);
        if (is_dir($backoffDirectory) && !is_link($path)) {
            @file_put_contents($path, json_encode(['until' => $now + $seconds]), LOCK_EX);
            @chmod($path, 0600);
        }
    }
    if ($result['status'] >= 400) error_log('RetroModem source status: ' . (parse_url($url, PHP_URL_HOST) ?: '') . ' HTTP ' . $result['status']);
    return $result;
}

function modemText($nl, $en) {
    return function_exists('retromodemNavigationLanguage') && retromodemNavigationLanguage() === 'nl' ? $nl : $en;
}

function modemUpstreamProblem($response) {
    if (isset($response['failure'])) return match ($response['failure']) {
        'timeout' => modemText('De bronwebsite antwoordde niet op tijd. Dit is een verbindingstime-out, geen interne proxyfout.', 'The source website did not answer in time. This is a connection timeout, not an internal proxy error.'),
        'tls' => modemText('De beveiligde verbinding met de bronwebsite kon niet worden opgebouwd. Certificaatcontrole blijft ingeschakeld.', 'The secure connection to the source website failed. Certificate verification remains enabled.'),
        'dns' => modemText('Het internetadres van de bronwebsite kon niet worden gevonden.', 'The source website could not be found in DNS.'),
        'blocked' => modemText('De proxy blokkeert een verwijzing naar een intern netwerkadres.', 'The proxy blocked a redirect to an internal network address.'),
        'size' => modemText('De bronpagina is groter dan de downloadlimiet.', 'The source page exceeds the download limit.'),
        'redirects' => modemText('De bronwebsite verwijst te vaak door.', 'The source website redirects too many times.'),
        default => modemText('De verbinding met de bronwebsite is mislukt. Probeer het later opnieuw.', 'The connection to the source website failed. Please try later.')
    };
    if ($response['status'] === 429) return modemText('De bronserver weigert tijdelijk toegang (HTTP 429). Dit kan ook een automatische bot- of IP-blokkade zijn; het betekent niet dat jij te vaak hebt geklikt. Nieuwe pogingen worden kort uitgesteld.', 'The source server temporarily refuses access (HTTP 429). This may also be an automated bot or IP restriction; it does not mean you clicked too often. New attempts are briefly deferred.');
    preg_match('/<title[^>]*>(.*?)<\/title>/is', $response['body'], $match);
    $title = html_entity_decode(strip_tags($match[1] ?? ''));
    if (preg_match('/just a moment|attention required|verify.*human|robot check|captcha/i', $title)) return modemText('De bronwebsite vraagt om een browsercontrole of CAPTCHA. De server weigert de eenvoudige proxy; dit is geen lokale adresblokkade.', 'The source website requires a browser check or CAPTCHA. The server refuses the simple proxy; this is not a local address block.');
    if (in_array($response['status'], [401, 403])) return modemText('De bronwebsite weigert toegang vanuit de proxy', 'The source website refuses access from the proxy') . ' (HTTP ' . $response['status'] . ').';
    if ($response['status'] >= 400) return modemText('De bronwebsite geeft een foutmelding', 'The source website returned an error') . ' (HTTP ' . $response['status'] . ').';
    if (strpos($response['type'], 'html') === false) return null;
    if (preg_match('/privacy gate|consent required|cookie consent/i', $title)) return modemText('De bronwebsite toont eerst een toestemmingspagina. Tracking wordt niet automatisch geaccepteerd.', 'The source website requires consent first. Tracking is not accepted automatically.');
    return null;
}
