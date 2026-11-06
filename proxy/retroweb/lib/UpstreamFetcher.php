<?php

namespace RetroWEB;

final class UpstreamFetcher
{
    public static function fetch(string $url, string $method, array $fields, UpstreamCookieJar $cookies): array
    {
        $method = strtoupper($method) === 'POST' ? 'POST' : 'GET';
        $body = $method === 'POST' ? LegacyFormConverter::encodeFields($fields) : null;
        $visited = [];
        for ($redirects = 0; $redirects <= MAX_REDIRECT_DEPTH; $redirects++) {
            if (\isInternalUrl($url) || isset($visited[$url])) throw new \RuntimeException('Unsafe or looping redirect');
            $visited[$url] = true;
            $cookie = $cookies->headerFor($url);
            $headers = [];
            if ($cookie !== null) $headers['Cookie'] = $cookie;
            [$data, $responseHeaders, $fetchedStatus] = SecureHttpClient::once($url, $method, $body, $headers, MAX_DOWNLOAD_SIZE);
            $cookies->capture($responseHeaders, $url);
            $status = $fetchedStatus; $location = null;
            foreach ($responseHeaders as $header) {
                if (preg_match('/^HTTP\/\S+\s+(\d{3})/', $header, $match)) $status = (int)$match[1];
                if (preg_match('/^Location:\s*(.+)$/i', $header, $match)) $location = trim($match[1]);
            }
            if ($status >= 300 && $status < 400 && $location !== null) {
                $next = \normalizeImageUrl($location, $url);
                if (!is_string($next) || !preg_match('/^https?:\/\//i', $next)) throw new \RuntimeException('Invalid redirect');
                if ($status === 303 || (($status === 301 || $status === 302) && $method === 'POST')) {
                    $method = 'GET'; $body = null;
                }
                $url = $next;
                continue;
            }
            return ['data'=>$data, 'headers'=>$responseHeaders, 'status'=>$status, 'url'=>$url, 'method'=>$method];
        }
        throw new \RuntimeException('Too many redirects');
    }

}
