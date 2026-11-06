<?php

namespace RetroWEB;

final class LegacyHtmlConverter
{
    public static function applyVisualOrder(string $html, string $sourceHtml = ''): string
    {
        $dom = new \DOMDocument('1.0', 'UTF-8');
        libxml_use_internal_errors(true);
        $loaded = $dom->loadHTML('<?xml encoding="UTF-8"><div id="retroweb-order-root">' . $html . '</div>', LIBXML_NONET);
        libxml_clear_errors();
        if (!$loaded) return $html;
        $xpath = new \DOMXPath($dom);
        $root = $xpath->query('//*[@id="retroweb-order-root"]')->item(0);
        if (!$root) return $html;

        $rules = self::simpleCssRules($sourceHtml);
        $containers = [];
        foreach ($xpath->query('.//*', $root) as $node) $containers[] = $node;
        foreach ($containers as $container) {
            if (!$container instanceof \DOMElement) continue;
            $style = self::effectiveStyle($container, $rules);
            if (!preg_match('/(?:^|;)\s*display\s*:\s*(?:inline-)?(flex|grid)\b/i', $style, $display)) continue;

            $children = [];
            $hasText = false;
            foreach ($container->childNodes as $child) {
                if ($child instanceof \DOMElement) $children[] = $child;
                elseif ($child instanceof \DOMText && trim($child->textContent) !== '') $hasText = true;
            }
            if ($hasText || count($children) < 2) continue;

            $areaPositions = strtolower($display[1]) === 'grid' ? self::gridAreaPositions($style) : [];
            $items = [];
            $hasOrder = false;
            $allAreas = $areaPositions !== [];
            foreach ($children as $index => $child) {
                $childStyle = self::effectiveStyle($child, $rules);
                $order = 0;
                if (preg_match('/(?:^|;)\s*order\s*:\s*(-?[0-9]{1,3})\b/i', $childStyle, $match)) {
                    $order = max(-999, min(999, (int)$match[1]));
                    $hasOrder = true;
                }
                $area = null;
                if (preg_match('/(?:^|;)\s*grid-area\s*:\s*([a-z_][a-z0-9_-]*)\b/i', $childStyle, $match)) {
                    $area = strtolower($match[1]);
                }
                if ($area === null || !isset($areaPositions[$area])) $allAreas = false;
                $items[] = ['node'=>$child, 'source'=>$index, 'order'=>$order,
                    'area'=>$area !== null && isset($areaPositions[$area]) ? $areaPositions[$area] : PHP_INT_MAX];
            }
            $reverse = preg_match('/(?:^|;)\s*flex-direction\s*:\s*(?:row|column)-reverse\b/i', $style) === 1;
            if (!$hasOrder && !$allAreas && !$reverse) continue;
            usort($items, function ($a, $b) use ($hasOrder, $allAreas, $reverse) {
                $comparison = $hasOrder ? ($a['order'] <=> $b['order']) : 0;
                if ($comparison === 0 && $allAreas) $comparison = $a['area'] <=> $b['area'];
                if ($comparison === 0) $comparison = $a['source'] <=> $b['source'];
                return $reverse ? -$comparison : $comparison;
            });
            foreach ($items as $item) $container->appendChild($item['node']);
        }
        return self::innerHtml($dom, $root);
    }

    public static function layoutMode(string $mode, string $htmlProfile): string
    {
        if ($mode !== 'auto') return $mode;
        return $htmlProfile === 'html4-lite' ? 'table' : 'flow';
    }

    public static function tableMode(string $mode, string $htmlProfile): string
    {
        if ($mode !== 'auto') return $mode;
        return $htmlProfile === 'html20' ? 'linearise' : 'table';
    }

    public static function convertTables(string $html, string $mode, string $htmlProfile): string
    {
        $mode = self::tableMode($mode, $htmlProfile);
        if (stripos($html, '<table') === false) return $html;

        $dom = new \DOMDocument('1.0', 'UTF-8');
        libxml_use_internal_errors(true);
        $loaded = $dom->loadHTML('<?xml encoding="UTF-8"><div id="retroweb-conversion-root">' . $html . '</div>', LIBXML_NONET);
        libxml_clear_errors();
        if (!$loaded) return $html;

        $xpath = new \DOMXPath($dom);
        $root = $xpath->query('//*[@id="retroweb-conversion-root"]')->item(0);
        if (!$root) return $html;

        $tables = [];
        foreach ($xpath->query('.//table', $root) as $table) $tables[] = $table;
        foreach (array_reverse($tables) as $table) {
            if (!$table->parentNode) continue;
            if ($mode === 'linearise') self::lineariseTable($dom, $table);
            else self::simplifyTable($xpath, $table);
        }

        return self::innerHtml($dom, $root);
    }

    public static function convertLayout(string $html, string $mode, string $htmlProfile, string $sourceHtml = ''): string
    {
        $mode = self::layoutMode($mode, $htmlProfile);
        if ($mode !== 'table') return $html;

        $dom = new \DOMDocument('1.0', 'UTF-8');
        libxml_use_internal_errors(true);
        $loaded = $dom->loadHTML('<?xml encoding="UTF-8"><div id="retroweb-layout-root">' . $html . '</div>', LIBXML_NONET);
        libxml_clear_errors();
        if (!$loaded) return $html;
        $xpath = new \DOMXPath($dom);
        $root = $xpath->query('//*[@id="retroweb-layout-root"]')->item(0);
        if (!$root) return $html;

        $rules = self::layoutRules($sourceHtml);
        $containers = [];
        foreach ($xpath->query('.//div | .//section | .//main | .//article', $root) as $node) $containers[] = $node;
        foreach (array_reverse($containers) as $container) {
            if (!$container instanceof \DOMElement || !$container->parentNode) continue;
            $style = $container->getAttribute('style');
            if (!preg_match('/display\s*:\s*(grid|flex)\b/i', $style, $display)) {
                $style = self::matchedLayoutStyle($container, $rules);
                if (!preg_match('/display\s*:\s*(grid|flex)\b/i', $style, $display)) continue;
            }
            $kind = strtolower($display[1]);
            if ($kind === 'flex' && preg_match('/flex-direction\s*:\s*column\b/i', $style)) continue;
            $children = [];
            foreach ($container->childNodes as $child) {
                if ($child instanceof \DOMElement || ($child instanceof \DOMText && trim($child->textContent) !== '')) $children[] = $child;
            }
            if (count($children) < 2) continue;

            $columns = $kind === 'grid' ? self::gridColumns($style) : min(4, count($children));
            $table = $dom->createElement('table');
            $table->setAttribute('border', '0');
            $table->setAttribute('cellspacing', '0');
            $table->setAttribute('cellpadding', '2');
            foreach ($children as $index => $child) {
                if ($index % $columns === 0) $row = $table->appendChild($dom->createElement('tr'));
                $cell = $row->appendChild($dom->createElement('td'));
                $cell->appendChild($child);
            }
            $container->parentNode->replaceChild($table, $container);
        }
        return self::innerHtml($dom, $root);
    }

    public static function preserveBlockSpacing(string $html): string
    {
        $html = preg_replace('/<figure\b[^>]*>/i', '<p>', $html);
        $html = preg_replace('/<\/figure\s*>/i', '</p>', $html);
        $html = preg_replace('/<figcaption\b[^>]*>/i', '<br><small>', $html);
        $html = preg_replace('/<\/figcaption\s*>/i', '</small>', $html);

        // These containers are removed by the legacy whitelist. Retain a
        // boundary only when their content is not already a block element.
        $html = preg_replace('/<\/(?:div|section|article|header|main|address)\s*>/i', '$0<br>', $html);
        $html = preg_replace('/<\/p>\s*<br\s*\/?>/i', '</p>', $html);
        $html = preg_replace('/<\/(h[1-6]|ul|ol|table)>\s*<br\s*\/?>/i', '</$1>', $html);
        $html = preg_replace('/(?:<br\s*\/?>\s*){2,}/i', '<br>', $html);
        return $html;
    }

    public static function normaliseBlockSpacing(string $html): string
    {
        $block = '(?:p|h[1-6]|ul|ol|table|blockquote)';
        $html = preg_replace('/(?:<br\s*\/?>\s*){2,}/i', '<br>', $html);
        $html = preg_replace('/(<\/' . $block . '>)\s*<br\s*\/?>/i', '$1', $html);
        $html = preg_replace('/<br\s*\/?>\s*(<' . $block . '\b)/i', '$1', $html);
        return $html;
    }

    public static function relocateMenus(string $html): string
    {
        $dom = new \DOMDocument('1.0', 'UTF-8');
        libxml_use_internal_errors(true);
        $loaded = $dom->loadHTML('<?xml encoding="UTF-8"><div id="retroweb-menu-root">' . $html . '</div>', LIBXML_NONET);
        libxml_clear_errors();
        if (!$loaded) return $html;
        $xpath = new \DOMXPath($dom);
        $root = $xpath->query('//*[@id="retroweb-menu-root"]')->item(0);
        if (!$root) return $html;

        $menus = [];
        foreach ($xpath->query('.//ul', $root) as $list) {
            if (!$list instanceof \DOMElement || self::hasMenuAncestor($list, $root)) continue;
            $semantic = false;
            for ($node = $list; $node instanceof \DOMElement && $node !== $root; $node = $node->parentNode) {
                $identity = trim($node->getAttribute('id') . ' ' . $node->getAttribute('class'));
                if (strtolower($node->getAttribute('role')) === 'navigation'
                    || preg_match('/(?:^|[\s_-])(?:menu|nav|navigation|sub-menu)(?:$|[\s_-])/i', $identity)) {
                    $semantic = true;
                    break;
                }
            }
            if (!$semantic && !$xpath->query('.//*[contains(concat(" ", normalize-space(@class), " "), " menu-item ")]', $list)->length) continue;
            $menus[] = $list;
        }
        if (!$menus) return $html;

        $hr = $dom->createElement('hr');
        $heading = $dom->createElement('h2', 'Menu');
        $root->appendChild($hr);
        $root->appendChild($heading);
        foreach ($menus as $menu) {
            if ($menu->parentNode) $root->appendChild($menu);
        }
        return self::innerHtml($dom, $root);
    }

    private static function hasMenuAncestor(\DOMElement $list, \DOMNode $root): bool
    {
        for ($node = $list->parentNode; $node instanceof \DOMElement && $node !== $root; $node = $node->parentNode) {
            if (strtolower($node->tagName) === 'ul') return true;
        }
        return false;
    }

    private static function layoutRules(string $html): array
    {
        $rules = [];
        if (!preg_match_all('/<style\b[^>]*>(.*?)<\/style>/is', $html, $blocks)) return $rules;
        foreach ($blocks[1] as $css) {
            if (!preg_match_all('/([^{}]+)\{([^{}]*display\s*:\s*(?:grid|flex)\b[^{}]*)\}/i', $css, $matches, PREG_SET_ORDER)) continue;
            foreach ($matches as $match) {
                foreach (explode(',', $match[1]) as $selector) {
                    $selector = trim($selector);
                    if (preg_match('/^[.#][a-z0-9_-]+$/i', $selector)) $rules[$selector] = $match[2];
                }
            }
        }
        return $rules;
    }

    private static function simpleCssRules(string $html): array
    {
        $rules = [];
        if (!preg_match_all('/<style\b[^>]*>(.*?)<\/style>/is', $html, $blocks)) return $rules;
        foreach ($blocks[1] as $css) {
            // Responsive and conditional blocks have no single visual order.
            // Remove them rather than guessing a viewport or feature set.
            $previous = null;
            while ($previous !== $css) {
                $previous = $css;
                $css = preg_replace('/@(media|supports|container|keyframes)[^{]*\{(?:[^{}]*|\{[^{}]*\})*\}/is', '', $css);
            }
            if (!preg_match_all('/([^{}]+)\{([^{}]*)\}/s', $css, $matches, PREG_SET_ORDER)) continue;
            foreach ($matches as $match) {
                foreach (explode(',', $match[1]) as $selector) {
                    $selector = trim(preg_replace('/\/\*.*?\*\//s', '', $selector));
                    if (!preg_match('/^(?:[a-z][a-z0-9-]*|[.#][a-z0-9_-]+)$/i', $selector)) continue;
                    $rules[$selector] = ($rules[$selector] ?? '') . ';' . $match[2];
                }
            }
        }
        return $rules;
    }

    private static function effectiveStyle(\DOMElement $element, array $rules): string
    {
        $styles = [];
        $tag = strtolower($element->tagName);
        if (isset($rules[$tag])) $styles[] = $rules[$tag];
        $id = $element->getAttribute('id');
        if ($id !== '' && isset($rules['#' . $id])) $styles[] = $rules['#' . $id];
        foreach (preg_split('/\s+/', trim($element->getAttribute('class'))) ?: [] as $class) {
            if ($class !== '' && isset($rules['.' . $class])) $styles[] = $rules['.' . $class];
        }
        if ($element->getAttribute('style') !== '') $styles[] = $element->getAttribute('style');
        return implode(';', $styles);
    }

    private static function gridAreaPositions(string $style): array
    {
        if (!preg_match('/(?:^|;)\s*grid-template-areas\s*:\s*((?:["\'][^"\']+["\']\s*)+)/i', $style, $match)) return [];
        if (!preg_match_all('/["\']([^"\']+)["\']/', $match[1], $rows)) return [];
        $positions = [];
        $position = 0;
        foreach ($rows[1] as $row) {
            foreach (preg_split('/\s+/', trim($row)) ?: [] as $area) {
                $area = strtolower($area);
                if ($area !== '.' && !isset($positions[$area])) $positions[$area] = $position;
                $position++;
            }
        }
        return $positions;
    }

    private static function matchedLayoutStyle(\DOMElement $element, array $rules): string
    {
        $styles = [];
        $id = $element->getAttribute('id');
        if ($id !== '' && isset($rules['#' . $id])) $styles[] = $rules['#' . $id];
        foreach (preg_split('/\s+/', trim($element->getAttribute('class'))) ?: [] as $class) {
            if ($class !== '' && isset($rules['.' . $class])) $styles[] = $rules['.' . $class];
        }
        return implode(';', $styles);
    }

    private static function gridColumns(string $style): int
    {
        if (!preg_match('/grid-template-columns\s*:\s*([^;]+)/i', $style, $match)) return 2;
        if (preg_match('/repeat\(\s*([1-4])\s*,/i', $match[1], $repeat)) return (int)$repeat[1];
        $tokens = preg_split('/\s+/', trim($match[1])) ?: [];
        return max(1, min(4, count($tokens)));
    }

    private static function simplifyTable(\DOMXPath $xpath, \DOMElement $table): void
    {
        foreach ($xpath->query('.//*[@style]', $table) as $element) {
            if (!$element instanceof \DOMElement) continue;
            $style = $element->getAttribute('style');
            $map = [
                'text-align' => 'align', 'vertical-align' => 'valign',
                'background-color' => 'bgcolor', 'width' => 'width', 'height' => 'height',
            ];
            foreach ($map as $property => $attribute) {
                if (preg_match('/(?:^|;)\s*' . preg_quote($property, '/') . '\s*:\s*([^;]+)/i', $style, $match)) {
                    $value = trim($match[1]);
                    if (preg_match('/^(?:#[0-9a-f]{3,6}|[a-z]+|[0-9]+%?|[0-9]+px)$/i', $value)) {
                        $element->setAttribute($attribute, preg_replace('/px$/i', '', $value));
                    }
                }
            }
            $element->removeAttribute('style');
        }

        $sections = [];
        foreach ($xpath->query('.//thead | .//tbody | .//tfoot', $table) as $section) $sections[] = $section;
        foreach ($sections as $section) {
            while ($section->firstChild) $section->parentNode->insertBefore($section->firstChild, $section);
            $section->parentNode->removeChild($section);
        }
    }

    private static function lineariseTable(\DOMDocument $dom, \DOMElement $table): void
    {
        $fragment = $dom->createDocumentFragment();
        $caption = self::firstDescendant($table, 'caption');
        if ($caption && trim($caption->textContent) !== '') {
            $p = $dom->createElement('p');
            $b = $dom->createElement('b');
            $b->appendChild($dom->createTextNode(trim($caption->textContent)));
            $p->appendChild($b);
            $fragment->appendChild($p);
        }

        $rows = $table->getElementsByTagName('tr');
        $headers = [];
        if ($rows->length > 0) {
            $firstCells = self::rowCells($rows->item(0));
            $headerOnly = $firstCells && count(array_filter($firstCells, fn($cell) => strtolower($cell->tagName) === 'th')) === count($firstCells);
            if ($headerOnly) foreach ($firstCells as $cell) $headers[] = trim($cell->textContent);

            foreach ($rows as $rowIndex => $row) {
                if ($rowIndex === 0 && $headerOnly) continue;
                $cells = self::rowCells($row);
                if (!$cells) continue;
                $p = $dom->createElement('p');
                foreach ($cells as $index => $cell) {
                    $label = $headers[$index] ?? (strtolower($cell->tagName) === 'th' ? trim($cell->textContent) : '');
                    if ($label !== '') {
                        $b = $dom->createElement('b');
                        $b->appendChild($dom->createTextNode($label . ': '));
                        $p->appendChild($b);
                    }
                    foreach (iterator_to_array($cell->childNodes) as $child) $p->appendChild($child->cloneNode(true));
                    if ($index < count($cells) - 1) $p->appendChild($dom->createElement('br'));
                }
                $fragment->appendChild($p);
            }
        }
        $table->parentNode->replaceChild($fragment, $table);
    }

    private static function rowCells(\DOMNode $row): array
    {
        $cells = [];
        foreach ($row->childNodes as $child) {
            if ($child instanceof \DOMElement && in_array(strtolower($child->tagName), ['th', 'td'], true)) $cells[] = $child;
        }
        return $cells;
    }

    private static function firstDescendant(\DOMElement $element, string $tag): ?\DOMElement
    {
        $node = $element->getElementsByTagName($tag)->item(0);
        return $node instanceof \DOMElement ? $node : null;
    }

    private static function innerHtml(\DOMDocument $dom, \DOMNode $node): string
    {
        $html = '';
        foreach ($node->childNodes as $child) $html .= $dom->saveHTML($child);
        return $html;
    }
}
