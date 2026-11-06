<?php
namespace RetroWEB;

final class ForwardProxyRequest
{
    public string $method;
    public string $url;
    public array $headers;
    public string $body;

    private function __construct(string $method, string $url, array $headers, string $body)
    {
        $this->method = $method;
        $this->url = $url;
        $this->headers = $headers;
        $this->body = $body;
    }

    public static function parse(string $raw): self
    {
        if (strlen($raw) > 81920) throw new \InvalidArgumentException('Request too large');
        $parts = preg_split('/\r?\n\r?\n/', $raw, 2);
        if (strlen($parts[0]) > 16384) throw new \InvalidArgumentException('Request headers too large');
        $lines = preg_split('/\r?\n/', $parts[0]);
        $body = $parts[1] ?? '';
        $requestLine = array_shift($lines);
        if (!is_string($requestLine) || !preg_match('/^(GET|HEAD|POST|CONNECT)\s+(\S+)\s+HTTP\/(1\.[01])$/i', $requestLine, $match)) {
            throw new \InvalidArgumentException('Unsupported request line');
        }
        $method = strtoupper($match[1]);
        if ($method === 'CONNECT') throw new \DomainException('CONNECT tunnelling is not supported');
        if (!preg_match('#^https?://#i', $match[2])) throw new \InvalidArgumentException('Absolute HTTP URL required');
        $headers = [];
        foreach ($lines as $line) {
            if ($line === '') break;
            if (!preg_match('/^([A-Za-z0-9-]+):\s*(.*)$/', $line, $header)) throw new \InvalidArgumentException('Malformed header');
            $name = strtolower($header[1]);
            if (in_array($name, ['proxy-authorization','authorization'], true)) continue;
            $headers[$name] = substr($header[2], 0, 2048);
        }
        if ($method === 'POST') {
            $length = isset($headers['content-length']) && preg_match('/^[0-9]+$/D', $headers['content-length'])
                ? (int)$headers['content-length'] : strlen($body);
            if ($length > 65536 || strlen($body) !== $length) throw new \InvalidArgumentException('Invalid or oversized POST body');
            $type = strtolower(trim(explode(';', $headers['content-type'] ?? '')[0]));
            if ($type !== 'application/x-www-form-urlencoded') throw new \DomainException('Only URL-encoded forms are supported');
            parse_str($body, $fields);
            foreach (array_keys($fields) as $name) {
                if (preg_match('/pass(?:word|wd)?|secret/i', (string)$name)) throw new \DomainException('Sensitive form fields are not supported');
            }
        } elseif ($body !== '') {
            throw new \InvalidArgumentException('Unexpected request body');
        }
        return new self($method, self::secureTarget($match[2]), $headers, $body);
    }

    public static function secureTarget(string $url): string
    {
        $parts = parse_url($url);
        if (!$parts || empty($parts['host']) || !in_array(strtolower($parts['scheme'] ?? ''), ['http','https'], true)) {
            throw new \InvalidArgumentException('Invalid target URL');
        }
        $scheme = strtolower($parts['scheme']);
        $port = $parts['port'] ?? ($scheme === 'https' ? 443 : 80);
        if (($scheme === 'http' && $port !== 80) || ($scheme === 'https' && $port !== 443)) {
            throw new \DomainException('Target port is not allowed');
        }
        $host = strtolower($parts['host']);
        $authority = str_contains($host, ':') ? '[' . trim($host, '[]') . ']' : $host;
        $path = $parts['path'] ?? '/';
        if ($path === '') $path = '/';
        return 'https://' . $authority . $path . (isset($parts['query']) ? '?' . $parts['query'] : '');
    }

    public function userAgent(): string
    {
        return $this->headers['user-agent'] ?? '';
    }
}
