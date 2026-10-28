<?php
/** Bounded image transport: validate and pin every redirect destination. */
class RetroWebImageFetcher
{
    private $resolver;
    private $transport;
    private $clock;
    private int $maxBytes;
    private int $timeoutMs;
    private int $redirects;
    private string $userAgent;

    public function __construct(int $maxBytes = 10485760, int $timeoutMs = 25000, int $redirects = 5,
                                string $userAgent = 'RetroModem/1.0', ?callable $resolver = null,
                                ?callable $transport = null, ?callable $clock = null)
    {
        $this->maxBytes = max(1, $maxBytes);
        $this->timeoutMs = max(1, $timeoutMs);
        $this->redirects = max(0, min(5, $redirects));
        $this->userAgent = $userAgent;
        $this->resolver = $resolver ?? [$this, 'resolve'];
        $this->transport = $transport ?? [$this, 'transfer'];
        $this->clock = $clock ?? fn() => microtime(true);
    }

    private function publicIp(string $ip): bool
    {
        if (!filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_NO_PRIV_RANGE | FILTER_FLAG_NO_RES_RANGE)) return false;
        if (strpos($ip, ':') !== false) {
            // Global unicast only: excludes mapped IPv4, link-local and NAT64.
            $packed = @inet_pton($ip);
            return $packed !== false && (ord($packed[0]) & 0xe0) === 0x20
                && strncmp(bin2hex($packed), '20010db8', 8) !== 0;
        }
        $octets = array_map('intval', explode('.', $ip));
        // PHP's legacy filter does not classify every special-use IPv4 range.
        if ($octets[0] === 0 || $octets[0] >= 224 || $octets[0] === 127) return false;
        if ($octets[0] === 100 && $octets[1] >= 64 && $octets[1] <= 127) return false;
        if ($octets[0] === 198 && in_array($octets[1], [18, 19], true)) return false;
        if (($octets[0] === 192 && $octets[1] === 0) || ($octets[0] === 198 && $octets[1] === 51 && $octets[2] === 100)
            || ($octets[0] === 203 && $octets[1] === 0 && $octets[2] === 113)) return false;
        return true;
    }

    private function destination(string $url): array
    {
        if (strlen($url) > 2048 || preg_match('/[\x00-\x20\x7f\\\\]/', $url)) throw new RuntimeException('', 403);
        $parts = parse_url($url);
        if (!is_array($parts) || !isset($parts['scheme'], $parts['host'])
            || !in_array(strtolower($parts['scheme']), ['http', 'https'], true)
            || isset($parts['user']) || isset($parts['pass'])) throw new RuntimeException('', 403);
        $host = strtolower(trim($parts['host'], '[]'));
        if ($host === '' || $host === 'localhost' || str_ends_with($host, '.localhost') || str_ends_with($host, '.local')) {
            throw new RuntimeException('', 403);
        }
        if (!filter_var($host, FILTER_VALIDATE_IP)
            && !preg_match('/^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9][a-z0-9-]{0,62}\.?$/D', $host)) {
            throw new RuntimeException('', 403);
        }
        $scheme = strtolower($parts['scheme']);
        $host = rtrim($host, '.');
        $port = $parts['port'] ?? ($scheme === 'https' ? 443 : 80);
        if ($port < 1 || $port > 65535) throw new RuntimeException('', 403);
        $authority = strpos($host, ':') !== false ? '[' . $host . ']' : $host;
        $canonical = $scheme . '://' . $authority . (isset($parts['port']) ? ':' . $port : '')
            . ($parts['path'] ?? '/') . (isset($parts['query']) ? '?' . $parts['query'] : '');
        return [$host, $port, $canonical];
    }

    /** GNU timeout bounds the libc resolver too; proc_open never invokes a shell. */
    private function resolve(string $host, int $timeoutMs): array
    {
        if (filter_var($host, FILTER_VALIDATE_IP)) return [$host];
        if (!is_executable('/usr/bin/timeout') || !is_executable('/usr/bin/getent') || !function_exists('proc_open')) {
            throw new RuntimeException('', 204);
        }
        $pipes = [];
        $seconds = (string)(max(1, min(3000, $timeoutMs)) / 1000);
        $process = proc_open(['/usr/bin/timeout', $seconds, '/usr/bin/getent', 'ahosts', $host],
                            [0 => ['file', '/dev/null', 'r'], 1 => ['pipe', 'w'], 2 => ['file', '/dev/null', 'w']], $pipes);
        if (!is_resource($process)) throw new RuntimeException('', 204);
        $output = stream_get_contents($pipes[1], 32769);
        fclose($pipes[1]);
        $status = proc_close($process);
        if ($status !== 0 || $output === false || strlen($output) > 32768) throw new RuntimeException('', 204);
        $addresses = [];
        foreach (preg_split('/\r?\n/', trim($output)) as $line) {
            $ip = preg_split('/\s+/', $line)[0] ?? '';
            if (filter_var($ip, FILTER_VALIDATE_IP)) $addresses[$ip] = true;
        }
        return array_keys($addresses);
    }

    private function redirectUrl(string $base, string $location): string
    {
        $location = trim($location);
        if ($location === '') throw new RuntimeException('', 204);
        if (preg_match('/^[a-z][a-z0-9+.-]*:/i', $location)) return $location;
        $parts = parse_url($base);
        $authority = $parts['scheme'] . '://' . $parts['host'] . (isset($parts['port']) ? ':' . $parts['port'] : '');
        if (str_starts_with($location, '//')) return $parts['scheme'] . ':' . $location;
        if ($location[0] === '?') return $authority . ($parts['path'] ?? '/') . $location;
        if ($location[0] === '#') return $base;
        $path = $location[0] === '/' ? $location : rtrim(dirname($parts['path'] ?? '/'), '/') . '/' . $location;
        $queryPosition = strcspn($path, '?#');
        $suffix = substr($path, $queryPosition);
        $segments = [];
        foreach (explode('/', substr($path, 0, $queryPosition)) as $segment) {
            if ($segment === '..') array_pop($segments);
            elseif ($segment !== '' && $segment !== '.') $segments[] = $segment;
        }
        $trailing = $segments && str_ends_with(substr($path, 0, $queryPosition), '/') ? '/' : '';
        return $authority . '/' . implode('/', $segments) . $trailing . $suffix;
    }

    private function transfer(array $request): array
    {
        if (!function_exists('curl_init')) throw new RuntimeException('', 204);
        $body = '';
        $headers = [];
        $oversized = false;
        $curl = curl_init($request['url']);
        $ip = strpos($request['ip'], ':') !== false ? '[' . $request['ip'] . ']' : $request['ip'];
        $options = [CURLOPT_FOLLOWLOCATION => false, CURLOPT_MAXREDIRS => 0,
            CURLOPT_PROTOCOLS => CURLPROTO_HTTP | CURLPROTO_HTTPS, CURLOPT_PROXY => '',
            CURLOPT_TIMEOUT_MS => $request['timeout_ms'], CURLOPT_CONNECTTIMEOUT_MS => min(5000, $request['timeout_ms']),
            CURLOPT_USERAGENT => $this->userAgent, CURLOPT_ENCODING => '', CURLOPT_SSL_VERIFYPEER => true,
            CURLOPT_SSL_VERIFYHOST => 2, CURLOPT_HTTPHEADER => ['Accept: image/*', 'Connection: close'],
            CURLOPT_HEADERFUNCTION => function ($handle, $line) use (&$headers, &$oversized, $request) {
                $parts = explode(':', $line, 2);
                if (count($parts) === 2) {
                    $name = strtolower(trim($parts[0]));
                    $value = trim($parts[1]);
                    $headers[$name] = $value;
                    if ($name === 'content-length' && ctype_digit($value) && (float)$value > $request['max_bytes']) {
                        $oversized = true;
                        return 0;
                    }
                }
                return strlen($line);
            },
            CURLOPT_WRITEFUNCTION => function ($handle, $chunk) use (&$body, &$oversized, $request) {
                if (strlen($body) + strlen($chunk) > $request['max_bytes']) {
                    $oversized = true;
                    return 0;
                }
                $body .= $chunk;
                return strlen($chunk);
            }];
        // Literal public IPs need no DNS override. Named hosts are pinned.
        if (!filter_var($request['host'], FILTER_VALIDATE_IP)) {
            $options[CURLOPT_RESOLVE] = [$request['host'] . ':' . $request['port'] . ':' . $ip];
        }
        curl_setopt_array($curl, $options);
        $ok = curl_exec($curl);
        $status = curl_getinfo($curl, CURLINFO_HTTP_CODE);
        curl_close($curl);
        if ($oversized) throw new RuntimeException('', 413);
        if ($ok === false) throw new RuntimeException('', 204);
        return ['status' => $status, 'headers' => $headers, 'body' => $body];
    }

    public function fetch(string $url): array
    {
        $empty = fn($status) => ['status' => $status, 'body' => '', 'type' => 'application/octet-stream', 'url' => ''];
        $deadline = ($this->clock)() + $this->timeoutMs / 1000;
        $downloaded = 0;
        try {
            for ($hop = 0; $hop <= $this->redirects; $hop++) {
                [$host, $port, $url] = $this->destination($url);
                $remaining = (int)floor(($deadline - ($this->clock)()) * 1000);
                if ($remaining <= 0) return $empty(204);
                $addresses = ($this->resolver)($host, $remaining);
                if (!$addresses) return $empty(204);
                foreach ($addresses as $ip) if (!is_string($ip) || !$this->publicIp($ip)) return $empty(403);
                $remaining = (int)floor(($deadline - ($this->clock)()) * 1000);
                if ($remaining <= 0) return $empty(204);
                if ($downloaded >= $this->maxBytes) return $empty(413);
                $response = ($this->transport)(['url' => $url, 'host' => $host, 'port' => $port, 'ip' => $addresses[0],
                    'max_bytes' => $this->maxBytes - $downloaded, 'timeout_ms' => $remaining, 'follow_redirects' => false]);
                if (($this->clock)() > $deadline) return $empty(204);
                if (!is_string($response['body'] ?? null)) return $empty(204);
                $downloaded += strlen($response['body']);
                if ($downloaded > $this->maxBytes) return $empty(413);
                $status = $response['status'] ?? 0;
                if (in_array($status, [301, 302, 303, 307, 308], true)) {
                    if ($hop === $this->redirects) return $empty(204);
                    $location = $response['headers']['location'] ?? '';
                    $url = $this->redirectUrl($url, $location);
                    continue;
                }
                if ($status !== 200 || $response['body'] === '') return $empty(204);
                $type = strtolower(trim(explode(';', $response['headers']['content-type'] ?? 'application/octet-stream')[0]));
                return ['status' => 200, 'body' => $response['body'], 'type' => $type, 'url' => $url];
            }
        } catch (Throwable $error) {
            return $empty(in_array($error->getCode(), [403, 413], true) ? $error->getCode() : 204);
        }
        return $empty(204);
    }
}
