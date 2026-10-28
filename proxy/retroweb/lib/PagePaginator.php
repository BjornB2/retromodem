<?php
/** Bounded HTML pages and stable, local snapshots for memory-limited browsers. */
class RetroWebPagePaginator
{
    private string $directory;
    private int $limit;
    private int $blockNumber = 0;
    private int $ttl;
    private int $maxDocuments;
    private int $maxCacheBytes;
    private string $language;
    private bool $weightImages = false;
    private const BRIDGE_RESERVE = 512;

    public function __construct(string $directory, int $limit = 250000, int $images = 5,
                                int $ttl = 3600, int $maxDocuments = 128, int $maxCacheBytes = 67108864,
                                string $language = 'en')
    {
        $this->directory = $directory;
        $this->limit = $limit;
        // $images is retained only for source compatibility. Image count must
        // never determine where article text is divided.
        $this->ttl = $ttl;
        $this->maxDocuments = $maxDocuments;
        $this->maxCacheBytes = $maxCacheBytes;
        $this->language = $language === 'nl' ? 'nl' : 'en';
    }

    private function tr(string $nl, string $en): string
    {
        return $this->language === 'nl' ? $nl : $en;
    }

    private function frame(string $title, string $navigation, string $bodyAttrs): array
    {
        return ["<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 2.0//EN\">\n<html><head>"
            . '<meta http-equiv="Content-Type" content="text/html; charset=iso-8859-1">'
            . '<title>' . $title . '</title></head><body' . $bodyAttrs . '>', '</body></html>'];
    }

    private function navigation(string $base, string $token, int $part, int $total,
                                string $mode, string $block, bool $all = false): string
    {
        $url = function ($selected, $imageMode, $sourceBlock = null) use ($base, $token) {
            $query = ['document' => $token, 'part' => (string)$selected, 'img' => $imageMode];
            if ($sourceBlock !== null) $query['block'] = $sourceBlock;
            return htmlspecialchars(rtrim($base, '/') . '/proxy.php?' . http_build_query($query), ENT_QUOTES, 'ISO-8859-1');
        };
        $images = $this->tr('Afbeeldingen: ', 'Images: ');
        foreach (['inline' => $this->tr('Laten zien', 'Inline'), 'links' => $this->tr('als links', 'As links')] as $value => $label) {
            if ($value !== 'inline') $images .= ' | ';
            $images .= $mode === $value ? '<b>' . $label . '</b>'
                : '<a href="' . $url($all ? 'all' : $part, $value, $all ? null : $block) . '">' . $label . '</a>';
        }
        if ($all) {
            return '<p class="retroweb-paging">' . $images . '<br><a href="' . $url(1, $mode)
                . '">' . $this->tr('Opdelen in pagina\'s', 'Show paginated page') . '</a></p><hr>';
        }
        $links = $this->tr('Deel ', 'Part ') . $part . $this->tr(' van ', ' of ') . $total;
        if ($part > 1) {
            $links .= ' | <a href="' . $url($part - 1, $mode) . '">&lt; ' . $this->tr('Vorige', 'Previous') . '</a>';
        }
        if ($part < $total) {
            $links .= ' | <a href="' . $url($part + 1, $mode) . '">' . $this->tr('Volgende', 'Next') . ' &gt;</a>';
        }
        return '<p class="retroweb-paging">' . $images . '<br>' . $links . ' | <a href="'
            . $url('all', $mode) . '">' . $this->tr('Volledige pagina tonen', 'Show entire page') . '</a></p><hr>';
    }

    private function document(string $content): array
    {
        $dom = new DOMDocument('1.0', 'UTF-8');
        $oldErrors = libxml_use_internal_errors(true);
        try {
            $dom->loadHTML('<?xml encoding="ISO-8859-1"><html><body><div id="retroweb-pagination-root">'
                . $content . '</div></body></html>', LIBXML_NONET);
        } finally {
            libxml_clear_errors();
            libxml_use_internal_errors($oldErrors);
        }
        $root = (new DOMXPath($dom))->query('//*[@id="retroweb-pagination-root"]')->item(0);
        if (!$root) throw new RuntimeException('Unable to parse pagination content');
        return [$dom, $root];
    }

    private function marker(): string
    {
        if (++$this->blockNumber > 999999) throw new RuntimeException('Too many document blocks');
        return '<!--rm-b' . $this->blockNumber . '-->';
    }

    /** Fine source markers survive both modes, even within one huge paragraph. */
    private function canonicalNode(DOMNode $node): string
    {
        if ($node instanceof DOMComment) return '';
        if ($node instanceof DOMText) {
            $output = '';
            foreach ($this->textPieces($node->nodeValue, 512) as $piece) {
                $output .= $this->marker() . $piece;
            }
            return $output;
        }
        if (!$node->hasChildNodes()) {
            return (strtolower($node->nodeName) === 'img' ? $this->marker() : '') . $this->serialize($node);
        }
        $wrapper = $this->serialize($node->cloneNode(false));
        $offset = strrpos($wrapper, '</');
        if ($offset === false) return $this->serialize($node);
        $output = substr($wrapper, 0, $offset);
        foreach ($node->childNodes as $child) $output .= $this->canonicalNode($child);
        return $output . substr($wrapper, $offset);
    }

    private function imageVariant(string $content, string $mode): string
    {
        [$dom, $root] = $this->document($content);
        $images = [];
        foreach ($root->getElementsByTagName('img') as $image) $images[] = $image;
        foreach ($images as $index => $image) {
            $image->setAttribute('data-rm-image-number', (string)($index + 1));
            if ($mode === 'links') {
                $label = $this->imageLabel($image);
                $replacement = $dom->createTextNode('[' . $label . ']');
                $ancestor = $image->parentNode;
                while ($ancestor && !($ancestor instanceof DOMElement && strtolower($ancestor->tagName) === 'a')) {
                    $ancestor = $ancestor->parentNode;
                }
                // A functional image link keeps its original destination.
                if (!$ancestor && $image->getAttribute('src') !== '') {
                    $link = $dom->createElement('a');
                    $link->setAttribute('href', $image->getAttribute('src'));
                    $link->appendChild($replacement);
                    $replacement = $link;
                }
                $image->parentNode->replaceChild($replacement, $image);
            }
        }
        $output = '';
        foreach ($root->childNodes as $child) $output .= $this->serialize($child);
        return $output;
    }

    private function imageLabel(DOMElement $image): string
    {
        $label = trim($image->getAttribute('data-rm-link-label'));
        if ($label !== '') {
            return preg_replace('/^(?:Image|Afbeelding)(?=\s+[0-9])/', $this->tr('Afbeelding', 'Image'), $label);
        }
        $label = $this->tr('Afbeelding ', 'Image ') . ($image->getAttribute('data-rm-image-number') ?: '1');
        if ($image->getAttribute('alt') !== '') $label .= ': ' . $image->getAttribute('alt');
        return $label;
    }

    private function imagePixels(string $tag): int
    {
        if (preg_match('/\sdata-rm-pixels=["\']([1-9][0-9]{0,9})["\']/i', $tag, $match)) {
            return (int)min(PHP_INT_MAX, (float)$match[1]);
        }
        $dimensions = [];
        foreach (['width', 'height'] as $name) {
            if (!preg_match('/\s' . $name . '=["\']([1-9][0-9]{0,7})["\']/i', $tag, $match)) {
                return 512 * 342;
            }
            $dimensions[] = (int)$match[1];
        }
        return (int)min(PHP_INT_MAX, (float)$dimensions[0] * $dimensions[1]);
    }

    private function cleanBody(string $html): string
    {
        $html = preg_replace('/<!--rm-(?:b[1-9][0-9]{0,5}|image-link)-->/', '', $html);
        return preg_replace('/\sdata-rm-(?:image-number|link-label)="[^"]*"/i', '', $html);
    }

    private function largeImageLink(DOMElement $image): string
    {
        $label = '[' . $this->imageLabel($image) . ']';
        $ancestor = $image->parentNode;
        while ($ancestor && !($ancestor instanceof DOMElement && strtolower($ancestor->tagName) === 'a')) {
            $ancestor = $ancestor->parentNode;
        }
        $text = htmlspecialchars($label, ENT_NOQUOTES, 'UTF-8');
        if (!$ancestor && $image->getAttribute('src') !== '') {
            $text = '<a href="' . htmlspecialchars($image->getAttribute('src'), ENT_QUOTES, 'UTF-8') . '">' . $text . '</a>';
        }
        return '<!--rm-image-link-->' . $this->latin1($text);
    }

    private function budgetNotice(int $count, bool $unlimited = false): string
    {
        if ($unlimited) {
            return '<p>' . $this->tr('Onverdeeld: kan veel geheugen gebruiken.', 'Unsplit: may use substantial memory.') . '</p>';
        }
        if ($count === 0) return '';
        return '<p>' . $count . $this->tr(' te grote afbeelding(en) als links weergegeven om binnen het geschatte budget te blijven.',
            ' oversized image(s) shown as links to stay within the estimated budget.') . '</p>';
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
        $currentBytes = 0;
        foreach ($fragments as $fragment) {
            $fragmentBytes = $this->htmlBytes($fragment);
            if ($current !== '' && $currentBytes + $fragmentBytes > $budget) {
                $pages[] = $current;
                $current = '';
                $currentBytes = 0;
            }
            $current .= $fragment;
            $currentBytes += $fragmentBytes;
        }
        if ($current !== '') {
            $pages[] = $current;
        }
        return $pages;
    }

    private function htmlBytes(string $html): int
    {
        // Internal source-position markers are removed before transmission.
        $html = $this->cleanBody($html);
        $weight = strlen($html);
        if ($this->weightImages) {
            preg_match_all('/<img\b[^>]*>/i', $html, $matches);
            foreach ($matches[0] as $image) $weight = (int)min(PHP_INT_MAX, (float)$weight + $this->imagePixels($image));
        }
        return $weight;
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
        if ($this->htmlBytes($serialized) <= $budget) {
            return [$serialized];
        }
        if (!$node->hasChildNodes()) {
            if ($this->weightImages && $node instanceof DOMElement && strtolower($node->tagName) === 'img') {
                $linked = $this->largeImageLink($node);
                if ($this->htmlBytes($linked) <= $budget) return [$linked];
            }
            // Oversized attributes (e.g. data URIs) cannot be split into valid
            // tags. Keep the original available in the explicit entire page.
            return ['<p>[' . $this->tr('Te groot onderdeel: gebruik Volledige pagina tonen', 'Oversized item: use Show entire page') . ']</p>'];
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
        $children = $this->childFragments($node, $innerBudget);
        return array_map(fn($part) => $opening . $part . $closing, $this->pack($children, $innerBudget));
    }

    private function childFragments(DOMNode $node, int $budget): array
    {
        $children = [];
        $pending = '';
        foreach ($node->childNodes as $child) {
            if ($child instanceof DOMComment && preg_match('/^rm-b[1-9][0-9]{0,5}$/D', $child->nodeValue)) {
                $pending .= $this->serialize($child);
                continue;
            }
            $pieces = $this->fragments($child, $budget);
            if ($pieces && $pending !== '') {
                $pieces[0] = $pending . $pieces[0];
                $pending = '';
            }
            array_push($children, ...$pieces);
        }
        return $children;
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

    private function renderVariant(string $canonical, string $title, string $navigation, string $bodyAttrs,
                                   string $baseUrl, string $token, string $mode): array
    {
        $this->weightImages = $mode === 'inline' && $this->limit !== 0;
        [$header, $footer] = $this->frame($title, $navigation, $bodyAttrs);
        $heading = '<h1>' . $title . '</h1>';
        $content = $this->imageVariant($canonical, $mode);
        $splitContent = preg_replace_callback('/href=(["\'])#([^"\']+)\1/i', function ($match) use ($baseUrl, $token, $mode) {
            $anchor = rawurldecode(html_entity_decode($match[2], ENT_QUOTES, 'ISO-8859-1'));
            $url = rtrim($baseUrl, '/') . '/proxy.php?document=' . $token . '&part=999999&img=' . $mode . '#' . rawurlencode($anchor);
            return 'href="' . htmlspecialchars($url, ENT_QUOTES, 'ISO-8859-1') . '"';
        }, $content);
        if ($this->limit === 0) {
            $parts = [$splitContent];
        } else {
            $reserve = 2 * max(strlen($this->navigation($baseUrl, $token, 999998, 999999, 'inline', 'b999999')),
                               strlen($this->navigation($baseUrl, $token, 999998, 999999, 'links', 'b999999')));
            $budget = $this->limit - self::BRIDGE_RESERVE - strlen($header) - strlen($heading) - strlen($footer)
                    - $reserve - strlen($this->budgetNotice(999999));
            if ($budget < 256) throw new RuntimeException('Pagination navigation exceeds page budget');
            [, $root] = $this->document($splitContent);
            $parts = $this->pack($this->childFragments($root, $budget), $budget);
            if (!$parts) $parts = [''];
        }
        $anchors = [];
        $blocks = [];
        $starts = [];
        foreach ($parts as $index => $part) {
            preg_match_all('/<!--rm-(b[1-9][0-9]{0,5})-->/', $part, $markers);
            $starts[] = $markers[1][0] ?? ($starts[$index - 1] ?? 'b1');
            foreach ($markers[1] as $block) $blocks[$block] ??= $index + 1;
            preg_match_all('/\b(?:id|name)=["\']([^"\']+)["\']/i', $part, $matches);
            foreach ($matches[1] as $anchor) {
                $anchor = html_entity_decode($anchor, ENT_QUOTES, 'ISO-8859-1');
                $anchors[$anchor] ??= $index + 1;
            }
        }
        $pages = [];
        $total = count($parts);
        foreach ($parts as $index => $part) {
            $part = preg_replace_callback('/href=(["\'])([^"\']+)\1/i', function ($match) use ($anchors, $baseUrl, $token, $mode) {
                $parsed = parse_url(html_entity_decode($match[2], ENT_QUOTES, 'ISO-8859-1'));
                parse_str($parsed['query'] ?? '', $query);
                if (($query['document'] ?? '') !== $token || ($query['part'] ?? '') !== '999999') return $match[0];
                $anchor = rawurldecode($parsed['fragment'] ?? '');
                if (!isset($anchors[$anchor])) return 'href="#' . htmlspecialchars($anchor, ENT_QUOTES, 'ISO-8859-1') . '"';
                $url = rtrim($baseUrl, '/') . '/proxy.php?document=' . $token . '&part=' . $anchors[$anchor]
                     . '&img=' . $mode . '#' . rawurlencode($anchor);
                return 'href="' . htmlspecialchars($url, ENT_QUOTES, 'ISO-8859-1') . '"';
            }, $part);
            $largeImages = substr_count($part, '<!--rm-image-link-->');
            $part = $this->cleanBody($part);
            $paging = $this->navigation($baseUrl, $token, $index + 1, $total, $mode, $starts[$index]);
            $notice = $this->budgetNotice($largeImages, $this->limit === 0);
            $page = $header . $paging . $notice . $heading . $part . $paging . $footer;
            if ($this->limit !== 0 && $this->htmlBytes($page) > $this->limit - self::BRIDGE_RESERVE) {
                throw new RuntimeException('Pagination page exceeded budget');
            }
            $pages[] = base64_encode($page);
        }
        $whole = $this->cleanBody($content);
        $paging = $this->navigation($baseUrl, $token, 1, $total, $mode, 'b1', true);
        return ['pages' => $pages, 'starts' => $starts, 'blocks' => $blocks,
                'all' => base64_encode($header . $paging . $this->budgetNotice(0, true) . $heading . $whole . $paging . $footer)];
    }

    private function save(string $token, array $snapshot): void
    {
        // Output is deliberately Latin-1 HTML, whereas JSON requires UTF-8.
        // Preserve framing bytes just as we already preserve content/pages.
        $stored = $snapshot;
        foreach (['title', 'navigation', 'body_attrs', 'base_url'] as $field) {
            if (!isset($stored[$field]) || !is_string($stored[$field])) {
                throw new RuntimeException('Invalid snapshot metadata');
            }
            $stored[$field] = base64_encode($stored[$field]);
        }
        $stored['metadata_encoding'] = 'base64';
        $encoded = json_encode($stored, JSON_THROW_ON_ERROR);
        if (!is_dir($this->directory) && !mkdir($this->directory, 0700, true) && !is_dir($this->directory)) {
            throw new RuntimeException('Pagination cache unavailable');
        }
        $lock = fopen($this->directory . '/.pagination.lock', 'c');
        if (!$lock || !flock($lock, LOCK_EX)) throw new RuntimeException('Pagination cache lock unavailable');
        $temporary = null;
        try {
            $this->prune(strlen($encoded));
            $temporary = tempnam($this->directory, '.pagination-');
            if (file_put_contents($temporary, $encoded, LOCK_EX) !== strlen($encoded)) {
                throw new RuntimeException('Unable to write pagination snapshot');
            }
            chmod($temporary, 0600);
            if (!rename($temporary, $this->snapshotPath($token))) throw new RuntimeException('Unable to publish pagination snapshot');
        } finally {
            if ($temporary !== null && is_file($temporary)) unlink($temporary);
            flock($lock, LOCK_UN);
            fclose($lock);
        }
    }

    public function first(string $content, string $title, string $navigation, string $bodyAttrs,
                          string $baseUrl, string $mode = 'inline'): string
    {
        if (!in_array($mode, ['inline', 'links'], true)) throw new RuntimeException('Invalid image mode');
        $token = hash('sha256', "retroweb-combined-v3\0" . $content . "\0" . $title . "\0" . $navigation
                    . "\0" . $bodyAttrs . "\0" . $baseUrl . "\0" . $this->limit . "\0" . $this->language);
        $existing = $this->read($token, '1', $mode);
        if ($existing['status'] === 200) return $existing['html'];
        [, $root] = $this->document($content);
        $this->blockNumber = 0;
        $canonical = '';
        foreach ($root->childNodes as $child) $canonical .= $this->canonicalNode($child);
        $variants = [];
        foreach (['inline', 'links'] as $imageMode) {
            $variants[$imageMode] = $this->renderVariant($canonical, $title, $navigation, $bodyAttrs, $baseUrl, $token, $imageMode);
        }
        $snapshot = ['schema_version' => 3, 'language' => $this->language, 'weight_policy' => 'html-plus-pixels-v4-compact-label',
                     'created' => time(), 'default_mode' => $mode,
                     'content' => base64_encode($canonical), 'title' => $title,
                     'navigation' => $navigation, 'body_attrs' => $bodyAttrs, 'base_url' => $baseUrl,
                     'limit' => $this->limit, 'variants' => $variants];
        $this->save($token, $snapshot);
        return base64_decode($variants[$mode]['pages'][0], true);
    }

    public function read(string $token, string $part, ?string $mode = null, ?string $block = null): array
    {
        $error = fn($status, $nl, $en) => ['status' => $status,
            'html' => '<html><head><title>RetroWEB</title></head><body><p>' . $this->tr($nl, $en) . '</p></body></html>'];
        if (!preg_match('/^[a-f0-9]{64}$/D', $token)
            || ($part !== 'all' && !preg_match('/^[1-9][0-9]{0,5}$/D', $part))
            || ($mode !== null && !in_array($mode, ['inline', 'links'], true))
            || ($block !== null && !preg_match('/^b[1-9][0-9]{0,5}$/D', $block))) {
            return $error(400, 'Ongeldige paginakeuze.', 'Invalid page selection.');
        }
        $path = $this->snapshotPath($token);
        if (is_link($path) || !is_file($path) || filesize($path) > $this->maxCacheBytes) {
            return $error(404, 'Pagina niet beschikbaar. Open de oorspronkelijke pagina opnieuw.',
                'Page snapshot unavailable. Open the original page again.');
        }
        $snapshot = json_decode(file_get_contents($path), true);
        if (!is_array($snapshot) || !isset($snapshot['created']) || !is_int($snapshot['created'])
            || $snapshot['created'] + $this->ttl < time()) {
            return $error(404, 'Pagina verlopen. Open de oorspronkelijke pagina opnieuw.',
                'Page snapshot expired. Open the original page again.');
        }
        if (($snapshot['metadata_encoding'] ?? null) === 'base64') {
            foreach (['title', 'navigation', 'body_attrs', 'base_url'] as $field) {
                $decoded = isset($snapshot[$field]) && is_string($snapshot[$field])
                    ? base64_decode($snapshot[$field], true) : false;
                if ($decoded === false) {
                    return $error(410, 'Pagina beschadigd. Open de oorspronkelijke pagina opnieuw.',
                        'Page snapshot damaged. Open the original page again.');
                }
                $snapshot[$field] = $decoded;
            }
        }
        if (!in_array($snapshot['schema_version'] ?? null, [2, 3], true)) {
            return $error(410, 'Deze oude pagina is vervallen. Open de oorspronkelijke pagina opnieuw.',
                'This old page has been retired. Open the original page again.');
        }
        // Rebuild old canonical snapshots locally under the current language
        // and combined-budget policy. Keep their original page-size setting.
        if (($snapshot['language'] ?? null) !== $this->language
            || ($snapshot['weight_policy'] ?? null) !== 'html-plus-pixels-v4-compact-label') {
            $canonical = isset($snapshot['content']) && is_string($snapshot['content'])
                ? base64_decode($snapshot['content'], true) : false;
            if ($canonical === false || !isset($snapshot['title'], $snapshot['navigation'], $snapshot['body_attrs'],
                $snapshot['base_url'], $snapshot['limit']) || !is_int($snapshot['limit']) || $snapshot['limit'] < 0) {
                return $error(410, 'Deze oude pagina kan niet worden aangepast. Open de oorspronkelijke pagina opnieuw.',
                    'This old page cannot be updated. Open the original page again.');
            }
            $currentLimit = $this->limit;
            $this->limit = $snapshot['limit'];
            try {
                $variants = [];
                foreach (['inline', 'links'] as $imageMode) {
                    $variants[$imageMode] = $this->renderVariant($canonical, $snapshot['title'], $snapshot['navigation'],
                        $snapshot['body_attrs'], $snapshot['base_url'], $token, $imageMode);
                }
                $snapshot['variants'] = $variants;
                $snapshot['schema_version'] = 3;
                $snapshot['language'] = $this->language;
                $snapshot['weight_policy'] = 'html-plus-pixels-v4-compact-label';
                $this->save($token, $snapshot);
            } catch (Throwable $failure) {
                return $error(503, 'De pagina kon niet opnieuw worden ingedeeld. Probeer het later opnieuw.',
                    'The page could not be divided again. Please try later.');
            } finally {
                $this->limit = $currentLimit;
            }
        }
        $mode ??= $snapshot['default_mode'] ?? 'inline';
        $variant = $snapshot['variants'][$mode] ?? null;
        if (!is_array($variant) || !isset($variant['pages'], $variant['all'], $variant['blocks'])) {
            return $error(404, 'Deze weergave is niet beschikbaar.', 'Page variant unavailable.');
        }
        if ($block !== null && $part !== 'all') {
            $mapped = $variant['blocks'][$block] ?? null;
            if (!is_int($mapped)) {
                return $error(404, 'Deze tekstpositie is niet beschikbaar.', 'Document position unavailable.');
            }
            $part = (string)$mapped;
        }
        $encoded = $part === 'all' ? $variant['all'] : ($variant['pages'][(int)$part - 1] ?? null);
        $html = is_string($encoded) ? base64_decode($encoded, true) : false;
        if ($html === false) return $error(404, 'Pagina niet gevonden.', 'Page not found.');
        if ($block !== null && $part !== 'all') {
            // Carry the requested logical position through a view round trip.
            // Replacing it by the destination page's earlier start would make
            // Inline -> Links -> Inline drift backward by one or more pages.
            $html = preg_replace_callback('/href=(["\'])([^"\']+)\1/i', function ($match) use ($token, $block) {
                $decoded = html_entity_decode($match[2], ENT_QUOTES, 'ISO-8859-1');
                $parsed = parse_url($decoded);
                parse_str($parsed['query'] ?? '', $query);
                if (($query['document'] ?? '') !== $token || !isset($query['block'])) return $match[0];
                return 'href="' . preg_replace_callback('/([?&](?:amp;)?block=)b[1-9][0-9]{0,5}/',
                    fn($position) => $position[1] . $block, $match[2]) . '"';
            }, $html);
        }
        return ['status' => 200, 'html' => $html];
    }
}
