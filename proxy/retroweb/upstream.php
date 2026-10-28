<?php
/** Transport for the embedded modem; the RetroWEB extractor remains unchanged. */
function fetchModemUpstream($url) {
    $cookieDir = sys_get_temp_dir() . '/retromodem-cookies';
    if (!is_dir($cookieDir)) {
        mkdir($cookieDir, 0700, true);
    }
    // One modem session, shared across redirects; libcurl enforces cookie domains.
    $jar = $cookieDir . '/session.txt';
    $result = null;
    for ($redirect = 0; $redirect < 8; $redirect++) {
        if (isInternalUrl($url)) {
            throw new RuntimeException('Redirect naar een intern adres geweigerd.');
        }
        $headers = [];
        $curl = curl_init($url);
        curl_setopt_array($curl, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_FOLLOWLOCATION => false,
            CURLOPT_CONNECTTIMEOUT => 8,
            CURLOPT_TIMEOUT => 25,
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
        curl_setopt($curl, CURLOPT_COOKIELIST, 'FLUSH');
        curl_close($curl);
        if ($body === false) throw new RuntimeException('Website reageert niet: ' . $error);
        if (strlen($body) > MAX_DOWNLOAD_SIZE) throw new RuntimeException('Pagina is te groot.');
        $result = ['url' => $url, 'body' => $body, 'status' => $status, 'type' => strtolower(explode(';', $type)[0])];
        if (in_array($status, [301, 302, 303, 307, 308]) && isset($headers['location'])) {
            $url = normalizeImageUrl($headers['location'], $url);
            continue;
        }
        return $result;
    }
    throw new RuntimeException('Te veel doorverwijzingen.');
}

function modemUpstreamProblem($response) {
    if ($response['status'] === 429) return 'De website ontvangt te veel verzoeken en vraagt om even te wachten.';
    if (in_array($response['status'], [401, 403])) return 'De website weigert toegang vanuit de proxy (HTTP ' . $response['status'] . ').';
    if ($response['status'] >= 400) return 'De website geeft een foutmelding (HTTP ' . $response['status'] . ').';
    if (strpos($response['type'], 'html') === false) return null;
    preg_match('/<title[^>]*>(.*?)<\/title>/is', $response['body'], $match);
    $title = html_entity_decode(strip_tags($match[1] ?? ''));
    if (preg_match('/privacy gate|consent required|cookie consent/i', $title)) return 'Deze website toont eerst een toestemmingspagina. De proxy accepteert tracking niet automatisch; daardoor is de inhoud nog niet bereikbaar.';
    if (preg_match('/just a moment|access denied|attention required|verify.*human|robot check|captcha/i', $title)) return 'Deze website vraagt om een browsercontrole of CAPTCHA die deze browser niet kan uitvoeren.';
    return null;
}
