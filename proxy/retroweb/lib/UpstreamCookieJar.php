<?php

namespace RetroWEB;

final class UpstreamCookieJar
{
    private array $cookies = [];

    public function __construct(private string $directory, private string $sessionId)
    {
        if (!preg_match('/^[a-f0-9]{32}$/', $sessionId)) throw new \InvalidArgumentException('Invalid session id');
        $path = $this->path();
        if (is_file($path) && filesize($path) <= 65536) {
            $decoded = json_decode((string)@file_get_contents($path), true);
            if (is_array($decoded)) $this->cookies = $decoded;
        }
        $this->purge();
    }

    public function headerFor(string $url): ?string
    {
        $parts = parse_url($url);
        if (!isset($parts['host'])) return null;
        $host = strtolower($parts['host']);
        $path = $parts['path'] ?? '/';
        $secure = strtolower($parts['scheme'] ?? '') === 'https';
        $pairs = [];
        foreach ($this->cookies as $cookie) {
            if (!self::domainMatches($host, $cookie['domain'] ?? '')) continue;
            if (!str_starts_with($path, $cookie['path'] ?? '/')) continue;
            if (!empty($cookie['secure']) && !$secure) continue;
            $pairs[] = $cookie['name'] . '=' . $cookie['value'];
        }
        return $pairs ? implode('; ', $pairs) : null;
    }

    public function capture(array $headers, string $url): void
    {
        $parts = parse_url($url);
        if (!isset($parts['host'])) return;
        $host = strtolower($parts['host']);
        $defaultPath = isset($parts['path']) ? rtrim(dirname($parts['path']), '/') . '/' : '/';
        foreach ($headers as $header) {
            if (!preg_match('/^Set-Cookie:\s*([^=;\s]+)=([^;]*)(.*)$/i', $header, $match)) continue;
            $name = $match[1]; $value = $match[2]; $attributes = $match[3];
            if (!preg_match('/^[!#$%&\'*+.^_`|~0-9A-Za-z-]{1,128}$/', $name) || strlen($value) > 4096) continue;
            $domain = $host; $path = $defaultPath; $expires = 0; $secure = false;
            foreach (explode(';', $attributes) as $attribute) {
                $attribute = trim($attribute);
                if (stripos($attribute, 'domain=') === 0) $domain = ltrim(strtolower(substr($attribute, 7)), '.');
                elseif (stripos($attribute, 'path=') === 0) $path = substr($attribute, 5) ?: '/';
                elseif (stripos($attribute, 'max-age=') === 0) $expires = time() + max(0, (int)substr($attribute, 8));
                elseif (stripos($attribute, 'expires=') === 0 && $expires === 0) $expires = strtotime(substr($attribute, 8)) ?: 0;
                elseif (strcasecmp($attribute, 'secure') === 0) $secure = true;
            }
            if (!self::domainMatches($host, $domain) || !str_starts_with($path, '/')) continue;
            $key = hash('sha256', $domain . "\0" . $path . "\0" . $name);
            if ($value === '' || ($expires > 0 && $expires <= time())) unset($this->cookies[$key]);
            else $this->cookies[$key] = compact('name','value','domain','path','expires','secure');
        }
        if (count($this->cookies) > 64) $this->cookies = array_slice($this->cookies, -64, null, true);
        $this->save();
    }

    private function purge(): void
    {
        $now = time();
        foreach ($this->cookies as $key => $cookie) if (($cookie['expires'] ?? 0) > 0 && $cookie['expires'] <= $now) unset($this->cookies[$key]);
    }

    private function save(): void
    {
        if (!is_dir($this->directory) && !@mkdir($this->directory, 0700, true) && !is_dir($this->directory)) return;
        $encoded = json_encode($this->cookies, JSON_UNESCAPED_SLASHES);
        if (is_string($encoded)) @file_put_contents($this->path(), $encoded, LOCK_EX);
    }

    private function path(): string { return rtrim($this->directory, '/') . '/' . $this->sessionId . '.json'; }
    private static function domainMatches(string $host, string $domain): bool { return $host === $domain || str_ends_with($host, '.' . $domain); }
}
