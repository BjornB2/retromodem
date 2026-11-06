<?php

namespace RetroWEB;

final class ImageCache
{
    public function __construct(
        private string $directory,
        private int $ttl = 86400,
        private int $maxFiles = 2000,
        private int $maxBytes = 268435456
    ) {}

    public function key(array $parameters): string
    {
        return hash('sha256', json_encode($parameters, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE));
    }

    public function get(string $key): ?string
    {
        $path = $this->path($key);
        if (!is_file($path)) return null;
        if ($this->ttl > 0 && filemtime($path) < time() - $this->ttl) {
            @unlink($path);
            @unlink($this->metadataPath($key));
            return null;
        }
        $data = @file_get_contents($path);
        return is_string($data) && $data !== '' ? $data : null;
    }

    public function put(string $key, string $data, array $metadata = []): bool
    {
        if ($data === '') return false;
        $path = $this->path($key);
        $directory = dirname($path);
        if (!is_dir($directory) && !@mkdir($directory, 0755, true) && !is_dir($directory)) return false;
        $temporary = @tempnam($directory, 'img-');
        if ($temporary === false) return false;
        $written = @file_put_contents($temporary, $data, LOCK_EX);
        if ($written !== strlen($data) || !@rename($temporary, $path)) {
            @unlink($temporary);
            return false;
        }
        @chmod($path, 0644);
        $this->putMetadata($key, $metadata);
        return true;
    }

    public function metadata(string $key): array
    {
        $path = $this->metadataPath($key);
        if (!is_file($path) || filesize($path) > 16384) return [];
        $data = json_decode((string)@file_get_contents($path), true);
        return is_array($data) ? $data : [];
    }

    public function putMetadata(string $key, array $metadata): bool
    {
        $path = $this->metadataPath($key);
        $directory = dirname($path);
        if (!is_dir($directory) && !@mkdir($directory, 0755, true) && !is_dir($directory)) return false;
        $allowed = array_intersect_key($metadata, array_flip(['etag','last_modified','source_hash','checked_at']));
        $encoded = json_encode($allowed, JSON_UNESCAPED_SLASHES);
        return is_string($encoded) && @file_put_contents($path, $encoded, LOCK_EX) === strlen($encoded);
    }

    public function prune(): array
    {
        $files = [];
        $bytes = 0;
        foreach (glob(rtrim($this->directory, '/') . '/*/*.gif') ?: [] as $path) {
            if (!is_file($path)) continue;
            $mtime = filemtime($path) ?: 0;
            if ($this->ttl > 0 && $mtime < time() - $this->ttl) {
                @unlink($path);
                @unlink(substr($path, 0, -4) . '.json');
                continue;
            }
            $size = filesize($path) ?: 0;
            $files[] = ['path'=>$path, 'mtime'=>$mtime, 'size'=>$size];
            $bytes += $size;
        }
        usort($files, fn($a, $b) => $a['mtime'] <=> $b['mtime']);
        $removed = 0;
        while (count($files) > $this->maxFiles || $bytes > $this->maxBytes) {
            $file = array_shift($files);
            if (@unlink($file['path'])) {
                @unlink(substr($file['path'], 0, -4) . '.json');
                $bytes -= $file['size']; $removed++;
            }
        }
        return ['files'=>count($files), 'bytes'=>$bytes, 'removed'=>$removed];
    }

    public function maybePrune(): void
    {
        try { if (random_int(1, 100) === 1) $this->prune(); } catch (\Throwable $ignored) {}
    }

    private function path(string $key): string
    {
        if (!preg_match('/^[a-f0-9]{64}$/', $key)) throw new \InvalidArgumentException('Invalid image cache key');
        return rtrim($this->directory, '/') . '/' . substr($key, 0, 2) . '/' . $key . '.gif';
    }

    private function metadataPath(string $key): string
    {
        return substr($this->path($key), 0, -4) . '.json';
    }
}
