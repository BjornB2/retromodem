<?php
namespace RetroWEB;

final class SecureHttpClient
{
    public static function request(string $url, string $method = 'GET', ?string $body = null, array $headers = [],
                                   int $maxBytes = MAX_DOWNLOAD_SIZE, int $maxRedirects = MAX_REDIRECT_DEPTH): array
    {
        $method = strtoupper($method);
        $visited = [];
        for ($redirects = 0; $redirects <= $maxRedirects; $redirects++) {
            if (isset($visited[$url]) || \isInternalUrl($url)) throw new \RuntimeException('Unsafe or looping redirect');
            $visited[$url] = true;
            [$data, $responseHeaders, $status] = self::once($url, $method, $body, $headers, $maxBytes);
            $location = self::header($responseHeaders, 'Location');
            if ($status >= 300 && $status < 400 && $location !== null) {
                $next = \normalizeImageUrl($location, $url);
                if (!is_string($next) || !preg_match('/^https?:\/\//i', $next)) throw new \RuntimeException('Invalid redirect');
                if ($status === 303 || (($status === 301 || $status === 302) && $method === 'POST')) {
                    $method = 'GET'; $body = null;
                }
                $url = $next;
                continue;
            }
            return ['data'=>$data,'headers'=>$responseHeaders,'status'=>$status,'url'=>$url,'method'=>$method];
        }
        throw new \RuntimeException('Too many redirects');
    }

    public static function once(string $url, string $method, ?string $body, array $headers, int $maxBytes): array
    {
        $addresses = \resolvePublicTargetAddresses($url);
        if (!$addresses) throw new \RuntimeException('Unsafe or unresolved target');
        if (!function_exists('curl_init')) throw new \RuntimeException('Secure HTTP transport unavailable');
        $parts = parse_url($url);
        $host = strtolower($parts['host']);
        $port = $parts['port'] ?? (strtolower($parts['scheme']) === 'https' ? 443 : 80);
        $requestHeaders = ['User-Agent: ' . USER_AGENT, 'Accept-Encoding: identity'];
        foreach ($headers as $name => $value) $requestHeaders[] = $name . ': ' . preg_replace('/[\r\n]/', '', (string)$value);
        $lastError = 'No address succeeded';
        foreach ($addresses as $address) {
            $responseHeaders = []; $data = '';
            $handle = curl_init($url);
            $pinned = $host . ':' . $port . ':' . (str_contains($address, ':') ? '[' . $address . ']' : $address);
            curl_setopt_array($handle, [
                CURLOPT_CUSTOMREQUEST=>$method, CURLOPT_HTTPHEADER=>$requestHeaders, CURLOPT_FOLLOWLOCATION=>false,
                CURLOPT_CONNECTTIMEOUT=>10, CURLOPT_TIMEOUT=>REQUEST_TIMEOUT, CURLOPT_PROTOCOLS=>CURLPROTO_HTTP|CURLPROTO_HTTPS,
                CURLOPT_RESOLVE=>[$pinned], CURLOPT_SSL_VERIFYPEER=>true, CURLOPT_SSL_VERIFYHOST=>2,
                CURLOPT_HEADERFUNCTION=>function($curl, $line) use (&$responseHeaders) {
                    $trimmed=trim($line); if($trimmed!=='')$responseHeaders[]=$trimmed; return strlen($line);
                },
                CURLOPT_WRITEFUNCTION=>function($curl, $chunk) use (&$data, $maxBytes) {
                    if(strlen($data)+strlen($chunk)>$maxBytes)return 0; $data.=$chunk; return strlen($chunk);
                },
            ]);
            // Some upstreams still announce or send a response body for HEAD.
            // Tell cURL explicitly not to read it; otherwise the small HEAD byte
            // limit can turn a successful metadata probe into a write error.
            if ($method === 'HEAD') curl_setopt($handle, CURLOPT_NOBODY, true);
            if ($body !== null) curl_setopt($handle, CURLOPT_POSTFIELDS, $body);
            $ok = curl_exec($handle);
            $lastError = curl_error($handle);
            $status = (int)curl_getinfo($handle, CURLINFO_RESPONSE_CODE);
            unset($handle);
            if ($ok !== false) return [$data, $responseHeaders, $status];
            if (strlen($data) >= $maxBytes) throw new \RuntimeException('Upstream response too large');
        }
        throw new \RuntimeException('Upstream request failed: ' . $lastError);
    }

    public static function header(array $headers, string $name): ?string
    {
        foreach (array_reverse($headers) as $header) {
            if (preg_match('/^' . preg_quote($name, '/') . ':\s*(.+)$/i', $header, $match)) return trim($match[1]);
        }
        return null;
    }
}
