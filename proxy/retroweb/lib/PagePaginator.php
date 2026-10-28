<?php
/** Bounded HTML pages and stable, local snapshots for memory-limited browsers. */
class RetroWebPagePaginator
{
    private string $directory;
    private int $limit;
    private int $images;
    private int $ttl;
    private int $maxDocuments;
    private int $maxCacheBytes;
    private const BRIDGE_RESERVE = 512;

    public function __construct(string $directory, int $limit = 18000, int $images = 5,
                                int $ttl = 3600, int $maxDocuments = 128, int $maxCacheBytes = 67108864)
    {
        $this->directory = $directory;
        $this->limit = $limit;
        $this->images = $images;
        $this->ttl = $ttl;
        $this->maxDocuments = $maxDocuments;
        $this->maxCacheBytes = $maxCacheBytes;
    }

    private function frame(string $title, string $navigation, string $bodyAttrs): array
    {
        return ["<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 2.0//EN\">\n<html><head>"
            . '<meta http-equiv="Content-Type" content="text/html; charset=iso-8859-1">'
            . '<title>' . $title . '</title></head><body' . $bodyAttrs . '>'
            . $navigation . '<h1>' . $title . '</h1>', '</body></html>'];
    }

    private function navigation(string $base, string $token, int $part, int $total): string
    {
        $prefix = htmlspecialchars(rtrim($base, '/') . '/proxy.php?document=' . $token . '&part=', ENT_QUOTES, 'ISO-8859-1');
        $links = 'Part ' . $part . ' of ' . $total;
        if ($part > 1) {
            $links .= ' | <a href="' . $prefix . ($part - 1) . '">&lt; Previous</a>';
        }
        if ($part < $total) {
            $links .= ' | <a href="' . $prefix . ($part + 1) . '">Next &gt;</a>';
        }
        return '<p class="retroweb-paging">' . $links . ' | <a href="' . $prefix . 'all">Show entire page</a></p><hr>';
    }

    private function imageCount(string $html): int
    {
        return preg_match_all('/<img\b/i', $html);
    }

    /** DOM uses UTF-8 internally; preserve non-Latin characters as numeric entities. */
    private function latin1(string $text): string
    {
        return mb_convert_encoding(mb_encode_numericentity($text, [256, 0x10ffff, 0, 0x1fffff], 'UTF-8'), 'ISO-8859-1', 'UTF-8');
    }

    private function serialize(DOMNode $node): string
    {
        return $this->latin1($node->ownerDocument->saveHTML($node));
    }

    private function textPieces(string $text, int $budget): array
    {
        $pieces = [];
        $current = '';
        $tokens = preg_split('/(\s+)/u', $text, -1, PREG_SPLIT_DELIM_CAPTURE | PREG_SPLIT_NO_EMPTY);
        foreach ($tokens as $token) {
            $encoded = $this->latin1(htmlspecialchars($token, ENT_NOQUOTES | ENT_SUBSTITUTE, 'UTF-8'));
            if (strlen($encoded) > $budget) {
                // An unbroken word still has to fit; never cut an HTML entity.
                foreach (preg_split('//u', $token, -1, PREG_SPLIT_NO_EMPTY) as $character) {
                    $character = $this->latin1(htmlspecialchars($character, ENT_NOQUOTES | ENT_SUBSTITUTE, 'UTF-8'));
                    if (strlen($current) + strlen($character) > $budget && $current !== '') {
                        $pieces[] = $current;
                        $current = '';
                    }
                    $current .= $character;
                }
                continue;
            }
            if (strlen($current) + strlen($encoded) > $budget && $current !== '') {
                $pieces[] = $current;
                $current = '';
            }
            $current .= $encoded;
        }
        if ($current !== '') {
            $pieces[] = $current;
        }
        return $pieces;
    }

    private function pack(array $fragments, int $budget): array
    {
        $pages = [];
        $current = '';
        $images = 0;
        foreach ($fragments as $fragment) {
            $count = $this->imageCount($fragment);
            if ($current !== '' && (strlen($current) + strlen($fragment) > $budget || $images + $count > $this->images)) {
                $pages[] = $current;
                $current = '';
                $images = 0;
            }
            $current .= $fragment;
            $images += $count;
        }
        if ($current !== '') {
            $pages[] = $current;
        }
        return $pages;
    }

    /** Split large elements recursively, reopening their ancestors in each part. */
    private function fragments(DOMNode $node, int $budget): array
    {
        if ($node instanceof DOMComment) {
            return [];
        }
        if ($node instanceof DOMText) {
            return $this->textPieces($node->nodeValue, $budget);
        }
        $serialized = $this->serialize($node);
        if (strlen($serialized) <= $budget && $this->imageCount($serialized) <= $this->images) {
            return [$serialized];
        }
        if (!$node->hasChildNodes()) {
            // Oversized attributes (e.g. data URIs) cannot be split into valid
            // tags. Keep the original available in the explicit entire page.
            return ['<p>[Oversized item: use Show entire page]</p>'];
        }
        $shell = $node->cloneNode(false);
        $wrapper = $this->serialize($shell);
        $closingOffset = strrpos($wrapper, '</');
        if ($closingOffset === false) {
            throw new RuntimeException('Cannot split this HTML element safely');
        }
        $opening = substr($wrapper, 0, $closingOffset);
        $closing = substr($wrapper, $closingOffset);
        $innerBudget = $budget - strlen($opening) - strlen($closing);
        if ($innerBudget < 64) {
            // Preserve text even when a pathological nesting/attribute chain
            // cannot itself fit. The original markup remains in entire page.
            return $this->textPieces($node->textContent, $budget);
        }
        $children = [];
        foreach ($node->childNodes as $child) {
            array_push($children, ...$this->fragments($child, $innerBudget));
        }
        return array_map(fn($part) => $opening . $part . $closing, $this->pack($children, $innerBudget));
    }

    private function snapshotPath(string $token): string
    {
        return $this->directory . '/pagination-' . $token . '.json';
    }

    private function prune(int $incoming): void
    {
        if (!is_dir($this->directory) && !mkdir($this->directory, 0700, true) && !is_dir($this->directory)) {
            throw new RuntimeException('Pagination cache unavailable');
        }
        $files = [];
        $bytes = 0;
        foreach (glob($this->directory . '/pagination-*.json') ?: [] as $path) {
            if (is_link($path) || !is_file($path)) {
                continue;
            }
            $mtime = filemtime($path);
            if ($mtime + $this->ttl < time()) {
                unlink($path);
                continue;
            }
            $size = filesize($path);
            $bytes += $size;
            $files[] = [$mtime, $path, $size];
        }
        usort($files, fn($a, $b) => $a[0] <=> $b[0]);
        while ($files && (count($files) >= $this->maxDocuments || $bytes + $incoming > $this->maxCacheBytes)) {
            [, $path, $size] = array_shift($files);
            unlink($path);
            $bytes -= $size;
        }
        if ($incoming > $this->maxCacheBytes) {
            throw new RuntimeException('Pagination snapshot too large');
        }
    }

    public function first(string $content, string $title, string $navigation, string $bodyAttrs, string $baseUrl): string
    {
        [$header, $footer] = $this->frame($title, $navigation, $bodyAttrs);
        $whole = $header . $content . $footer;
        if ($this->limit === 0 || (strlen($whole) <= $this->limit - self::BRIDGE_RESERVE && $this->imageCount($content) <= $this->images)) {
            return $whole;
        }
        $token = hash('sha256', $whole . "\0" . $baseUrl . "\0" . $this->limit . ':' . $this->images);
        $existing = $this->read($token, '1');
        if ($existing['status'] === 200) {
            return $existing['html'];
        }
        // Reserve both complete navigation bars with conservative digit counts.
        $reserve = 2 * strlen($this->navigation($baseUrl, $token, 999998, 999999));
        $budget = $this->limit - self::BRIDGE_RESERVE - strlen($header) - strlen($footer) - $reserve;
        if ($budget < 256) {
            throw new RuntimeException('Pagination navigation exceeds page budget');
        }
        $dom = new DOMDocument('1.0', 'UTF-8');
        // Reserve the complete cross-part link before splitting, then shorten
        // its page placeholder once the target anchor's part is known.
        $splitContent = preg_replace_callback('/href=(["\'])#([^"\']+)\1/i', function ($match) use ($baseUrl, $token) {
            $anchor = rawurldecode(html_entity_decode($match[2], ENT_QUOTES, 'ISO-8859-1'));
            $url = rtrim($baseUrl, '/') . '/proxy.php?document=' . $token . '&part=999999#' . rawurlencode($anchor);
            return 'href="' . htmlspecialchars($url, ENT_QUOTES, 'ISO-8859-1') . '"';
        }, $content);
        $oldErrors = libxml_use_internal_errors(true);
        try {
            $dom->loadHTML('<?xml encoding="ISO-8859-1"><html><body><div id="retroweb-pagination-root">' . $splitContent . '</div></body></html>', LIBXML_NONET);
        } finally {
            libxml_clear_errors();
            libxml_use_internal_errors($oldErrors);
        }
        $root = (new DOMXPath($dom))->query('//*[@id="retroweb-pagination-root"]')->item(0);
        if (!$root) {
            throw new RuntimeException('Unable to parse pagination content');
        }
        $fragments = [];
        foreach ($root->childNodes as $child) {
            array_push($fragments, ...$this->fragments($child, $budget));
        }
        $parts = $this->pack($fragments, $budget);
        if (!$parts) {
            $parts = [''];
        }
        $total = count($parts);
        $anchors = [];
        foreach ($parts as $index => $part) {
            preg_match_all('/\b(?:id|name)=["\']([^"\']+)["\']/i', $part, $matches);
            foreach ($matches[1] as $anchor) {
                $anchor = html_entity_decode($anchor, ENT_QUOTES, 'ISO-8859-1');
                $anchors[$anchor] ??= $index + 1;
            }
        }
        foreach ($parts as &$part) {
            $part = preg_replace_callback('/href=(["\'])([^"\']+)\1/i', function ($match) use ($anchors, $baseUrl, $token) {
                $parsed = parse_url(html_entity_decode($match[2], ENT_QUOTES, 'ISO-8859-1'));
                parse_str($parsed['query'] ?? '', $query);
                if (($query['document'] ?? '') !== $token || ($query['part'] ?? '') !== '999999') {
                    return $match[0];
                }
                $anchor = rawurldecode($parsed['fragment'] ?? '');
                if (!isset($anchors[$anchor])) {
                    return 'href="#' . htmlspecialchars($anchor, ENT_QUOTES, 'ISO-8859-1') . '"';
                }
                $url = rtrim($baseUrl, '/') . '/proxy.php?document=' . $token . '&part=' . $anchors[$anchor] . '#' . rawurlencode($anchor);
                return 'href="' . htmlspecialchars($url, ENT_QUOTES, 'ISO-8859-1') . '"';
            }, $part);
        }
        unset($part);
        $pages = [];
        foreach ($parts as $index => $part) {
            $paging = $this->navigation($baseUrl, $token, $index + 1, $total);
            $page = $header . $paging . $part . $paging . $footer;
            if (strlen($page) > $this->limit - self::BRIDGE_RESERVE || $this->imageCount($part) > $this->images) {
                throw new RuntimeException('Pagination page exceeded budget');
            }
            $pages[] = base64_encode($page);
        }
        $back = '<p><a href="' . htmlspecialchars(rtrim($baseUrl, '/') . '/proxy.php?document=' . $token . '&part=1', ENT_QUOTES, 'ISO-8859-1') . '">Show paginated page</a></p>';
        $snapshot = json_encode(['created' => time(), 'pages' => $pages, 'all' => base64_encode($header . $back . $content . $back . $footer)], JSON_THROW_ON_ERROR);
        if (!is_dir($this->directory) && !mkdir($this->directory, 0700, true) && !is_dir($this->directory)) {
            throw new RuntimeException('Pagination cache unavailable');
        }
        $lock = fopen($this->directory . '/.pagination.lock', 'c');
        if (!$lock || !flock($lock, LOCK_EX)) {
            throw new RuntimeException('Pagination cache lock unavailable');
        }
        $temporary = null;
        try {
            $this->prune(strlen($snapshot));
            $temporary = tempnam($this->directory, '.pagination-');
            if (file_put_contents($temporary, $snapshot, LOCK_EX) !== strlen($snapshot)) {
                throw new RuntimeException('Unable to write pagination snapshot');
            }
            chmod($temporary, 0600);
            if (!rename($temporary, $this->snapshotPath($token))) {
                throw new RuntimeException('Unable to publish pagination snapshot');
            }
        } finally {
            if ($temporary !== null && is_file($temporary)) {
                unlink($temporary);
            }
            flock($lock, LOCK_UN);
            fclose($lock);
        }
        return base64_decode($pages[0], true);
    }

    public function read(string $token, string $part): array
    {
        $error = fn($status, $message) => ['status' => $status, 'html' => '<html><head><title>RetroWEB</title></head><body><p>' . $message . '</p></body></html>'];
        if (!preg_match('/^[a-f0-9]{64}$/D', $token) || ($part !== 'all' && !preg_match('/^[1-9][0-9]{0,5}$/D', $part))) {
            return $error(400, 'Invalid page selection.');
        }
        $path = $this->snapshotPath($token);
        if (is_link($path) || !is_file($path) || filesize($path) > $this->maxCacheBytes) {
            return $error(404, 'Page snapshot unavailable. Open the original link again.');
        }
        $snapshot = json_decode(file_get_contents($path), true);
        if (!is_array($snapshot) || !isset($snapshot['created'], $snapshot['pages'], $snapshot['all'])
            || !is_int($snapshot['created']) || !is_array($snapshot['pages']) || !is_string($snapshot['all'])
            || $snapshot['created'] + $this->ttl < time()) {
            return $error(404, 'Page snapshot expired. Open the original link again.');
        }
        $encoded = $part === 'all' ? $snapshot['all'] : ($snapshot['pages'][(int)$part - 1] ?? null);
        $html = is_string($encoded) ? base64_decode($encoded, true) : false;
        if ($html === false) {
            return $error(404, 'Page not found.');
        }
        return ['status' => 200, 'html' => $html];
    }
}
