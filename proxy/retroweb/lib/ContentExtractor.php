<?php
/**
 * RetroWEB - Content Extractor Interface and Implementations
 */

namespace RetroWEB;

/**
 * Interface voor content extractors
 */
interface ContentExtractorInterface {
    /**
     * Extract title en content uit HTML
     * @param string $html HTML content
     * @param string $url Originele URL (voor relatieve link normalisatie)
     * @return array ['title' => string, 'content' => string] of false bij falen
     */
    public function extract($html, $url = '');
}

/**
 * Base class voor extractors
 */
abstract class BaseContentExtractor implements ContentExtractorInterface {
    /**
     * Strip bekende noise elementen uit HTML
     * @param string $html HTML content
     * @return string Gefilterde HTML
     */
    protected function stripNoise($html) {
        // Noise patterns (class/id names die meestal niet-content zijn)
        $noisePatterns = [
            'nav', 'navigation', 'menu', 'sidebar', 'aside',
            'footer', 'header', 'advertisement', 'ad', 'ads',
            'social', 'share', 'comment', 'comments', 'related',
            'breadcrumb', 'breadcrumbs', 'pagination', 'pager',
            'widget', 'widgets', 'popup', 'modal', 'overlay',
            'cookie', 'consent', 'newsletter', 'subscribe'
        ];
        
        // Strip elementen met noise classes/ids
        foreach ($noisePatterns as $pattern) {
            $html = preg_replace('/<[^>]+(?:class|id)=["\'][^"\']*' . preg_quote($pattern, '/') . '[^"\']*["\'][^>]*>.*?<\/[^>]+>/is', '', $html);
        }
        
        return $html;
    }
    
    /**
     * Normaliseer HTML voor parsing
     * @param string $html HTML content
     * @return string Genormaliseerde HTML
     */
    protected function normalizeHtml($html) {
        // Fix encoding issues
        $html = mb_convert_encoding($html, 'HTML-ENTITIES', 'UTF-8');
        
        // Add XML declaration voor DOMDocument
        if (strpos($html, '<?xml') === false) {
            $html = '<?xml encoding="UTF-8">' . $html;
        }
        
        return $html;
    }
}

/**
 * Custom DOM-based extractor die meer content behoudt
 */
class CustomDOMExtractor extends BaseContentExtractor {
    private $minContentLength = 200; // Minimum content lengte in karakters
    
    public function __construct($minContentLength = 200) {
        $this->minContentLength = $minContentLength;
    }
    
    public function extract($html, $url = '') {
        try {
            $html = $this->normalizeHtml($html);
            
            // Load HTML in DOMDocument
            libxml_use_internal_errors(true);
            $dom = new \DOMDocument('1.0', 'UTF-8');
            @$dom->loadHTML($html);
            libxml_clear_errors();
            
            $xpath = new \DOMXPath($dom);
            
            // Eerst proberen semantische HTML5 tags
            $contentNodes = [];
            
            // Prefer the page's explicit main landmark. On overview pages,
            // articles can be individual headlines rather than the whole page.
            $mains = $xpath->query('//main | //*[@role="main"]');
            foreach ($mains as $main) {
                $nested = false;
                for ($parent = $main->parentNode; $parent instanceof \DOMElement; $parent = $parent->parentNode) {
                    if ($parent->tagName === 'main' || $parent->getAttribute('role') === 'main') {
                        $nested = true;
                        break;
                    }
                }
                if (!$nested) {
                    $contentNodes[] = $main;
                }
            }

            // Without a main landmark, retain outer articles only: nested
            // articles are already included in their parent's serialized HTML.
            if (empty($contentNodes)) {
                $articles = $xpath->query('//article[not(ancestor::article)]');
                foreach ($articles as $article) {
                    $contentNodes[] = $article;
                }
            }
            
            // Prioriteit 3: <section> tags met veel content
            if (empty($contentNodes)) {
                $sections = $xpath->query('//section');
                foreach ($sections as $section) {
                    $text = $this->getTextContent($section);
                    if (strlen($text) >= $this->minContentLength) {
                        $contentNodes[] = $section;
                    }
                }
            }
            
            // Prioriteit 4: <div> tags met veel content (maar geen noise)
            if (empty($contentNodes)) {
                $divs = $xpath->query('//div[not(ancestor::nav) and not(ancestor::header) and not(ancestor::footer) and not(ancestor::aside)]');
                $scoredDivs = [];
                
                foreach ($divs as $div) {
                    $score = $this->scoreNode($div, $xpath);
                    if ($score > 0) {
                        $scoredDivs[] = ['node' => $div, 'score' => $score];
                    }
                }
                
                // Sorteer op score (hoogste eerst)
                usort($scoredDivs, function($a, $b) {
                    return $b['score'] - $a['score'];
                });
                
                // Neem top 3 nodes met hoogste score
                foreach (array_slice($scoredDivs, 0, 3) as $item) {
                    $text = $this->getTextContent($item['node']);
                    if (strlen($text) >= $this->minContentLength) {
                        $contentNodes[] = $item['node'];
                    }
                }
            }
            
            // Als nog steeds geen content, gebruik body
            if (empty($contentNodes)) {
                $body = $xpath->query('//body')->item(0);
                if ($body) {
                    $contentNodes[] = $body;
                }
            }
            
            // Combineer alle content nodes
            $content = '';
            foreach ($contentNodes as $node) {
                $content .= $dom->saveHTML($node);
            }
            
            // Als content te kort is, gebruik originele HTML (maar gefilterd)
            if (strlen(strip_tags($content)) < $this->minContentLength) {
                $body = $xpath->query('//body')->item(0);
                if ($body) {
                    $content = $dom->saveHTML($body);
                } else {
                    $content = $html;
                }
            }
            
            // Extract title
            $title = $this->extractTitle($dom, $xpath);
            
            return [
                'title' => $title,
                'content' => $content
            ];
            
        } catch (\Exception $e) {
            error_log('CustomDOMExtractor error: ' . $e->getMessage());
            return false;
        }
    }
    
    /**
     * Score een node op basis van content kwaliteit
     * @param \DOMNode $node
     * @param \DOMXPath $xpath
     * @return int Score (hoger = beter)
     */
    private function scoreNode($node, $xpath) {
        $score = 0;
        
        // Haal tekst content op
        $text = $this->getTextContent($node);
        $textLength = strlen($text);
        
        // Basis score op tekst lengte
        $score += min($textLength / 10, 100); // Max 100 punten voor lengte
        
        // Tel aantal paragrafen
        $paragraphs = $xpath->query('.//p', $node);
        $score += $paragraphs->length * 5;
        
        // Tel aantal headings
        $headings = $xpath->query('.//h1 | .//h2 | .//h3 | .//h4 | .//h5 | .//h6', $node);
        $score += $headings->length * 10;
        
        // Tel aantal links (te veel links = waarschijnlijk navigatie)
        $links = $xpath->query('.//a', $node);
        $linkCount = $links->length;
        $linkRatio = $textLength > 0 ? ($linkCount / ($textLength / 100)) : 0;
        
        // Penaliseer te veel links (navigatie heeft veel links)
        if ($linkRatio > 2) {
            $score -= 50; // Grote penalty voor navigatie-achtige content
        } elseif ($linkRatio > 1) {
            $score -= 20;
        }
        
        // Bonus voor semantische tags
        $semanticTags = $xpath->query('.//article | .//section | .//main', $node);
        $score += $semanticTags->length * 15;
        
        // Penaliseer noise elementen
        $noiseElements = $xpath->query('.//nav | .//aside | .//footer | .//header', $node);
        $score -= $noiseElements->length * 30;
        
        // Check class/id voor noise patterns
        $class = $node->getAttribute('class');
        $id = $node->getAttribute('id');
        $noisePatterns = ['nav', 'menu', 'sidebar', 'footer', 'header', 'ad', 'widget'];
        foreach ($noisePatterns as $pattern) {
            if (stripos($class, $pattern) !== false || stripos($id, $pattern) !== false) {
                $score -= 100; // Grote penalty
            }
        }
        
        return max(0, $score); // Geen negatieve scores
    }
    
    /**
     * Haal tekst content uit node (zonder HTML tags)
     * @param \DOMNode $node
     * @return string Tekst content
     */
    private function getTextContent($node) {
        $text = '';
        foreach ($node->childNodes as $child) {
            if ($child->nodeType === XML_TEXT_NODE) {
                $text .= $child->textContent;
            } elseif ($child->nodeType === XML_ELEMENT_NODE) {
                $text .= $this->getTextContent($child);
            }
        }
        return trim($text);
    }
    
    /**
     * Extract title uit DOM
     * @param \DOMDocument $dom
     * @param \DOMXPath $xpath
     * @return string Title
     */
    private function extractTitle($dom, $xpath) {
        // Probeer <title> tag
        $titles = $xpath->query('//title');
        if ($titles->length > 0) {
            $title = trim($titles->item(0)->textContent);
            if (!empty($title)) {
                return $title;
            }
        }
        
        // Probeer <h1> tag
        $h1s = $xpath->query('//h1');
        if ($h1s->length > 0) {
            $title = trim($h1s->item(0)->textContent);
            if (!empty($title) && strlen($title) < 200) {
                return $title;
            }
        }
        
        // Probeer meta og:title
        $metaOgTitle = $xpath->query('//meta[@property="og:title"]/@content');
        if ($metaOgTitle->length > 0) {
            $title = trim($metaOgTitle->item(0)->value);
            if (!empty($title)) {
                return $title;
            }
        }
        
        return 'Page';
    }
}

/**
 * Readability extractor wrapper
 */
class ReadabilityExtractor extends BaseContentExtractor {
    public function extract($html, $url = '') {
        try {
            // Check of Readability beschikbaar is
            if (!class_exists('fivefilters\Readability\Readability')) {
                error_log('Readability class not found');
                return false;
            }
            
            $html = $this->normalizeHtml($html);
            
            $config = new \fivefilters\Readability\Configuration();
            $readability = new \fivefilters\Readability\Readability($config);
            
            $parseResult = $readability->parse($html);
            
            if ($parseResult === false) {
                return false;
            }
            
            $title = $readability->getTitle();
            $content = $readability->getContent();
            
            if (empty($content)) {
                return false;
            }
            
            return [
                'title' => $title ?: 'Page',
                'content' => $content
            ];
            
        } catch (\Exception $e) {
            error_log('ReadabilityExtractor error: ' . $e->getMessage());
            return false;
        }
    }
}

/**
 * Hybrid extractor die meerdere extractors combineert
 */
class HybridExtractor extends BaseContentExtractor {
    private $extractors = [];
    
    public function __construct() {
        // Probeer eerst Readability (als beschikbaar)
        if (class_exists('fivefilters\Readability\Readability')) {
            $this->extractors[] = new ReadabilityExtractor();
        }
        
        // Fallback naar CustomDOMExtractor
        $this->extractors[] = new CustomDOMExtractor();
    }
    
    public function extract($html, $url = '') {
        $lastResult = false;
        
        foreach ($this->extractors as $extractor) {
            $result = $extractor->extract($html, $url);
            
            if ($result !== false) {
                // Check of content lang genoeg is
                $textContent = strip_tags($result['content']);
                if (strlen($textContent) >= 200) {
                    return $result; // Goed resultaat
                }
                // Bewaar als fallback
                $lastResult = $result;
            }
        }
        
        // Als alle extractors faalden, gebruik laatste resultaat of originele HTML
        if ($lastResult !== false) {
            return $lastResult;
        }
        
        // Laatste fallback: gebruik originele HTML
        $html = $this->normalizeHtml($html);
        libxml_use_internal_errors(true);
        $dom = new \DOMDocument('1.0', 'UTF-8');
        @$dom->loadHTML($html);
        libxml_clear_errors();
        
        $xpath = new \DOMXPath($dom);
        $body = $xpath->query('//body')->item(0);
        $title = 'Page';
        
        $titles = $xpath->query('//title');
        if ($titles->length > 0) {
            $title = trim($titles->item(0)->textContent);
        }
        
        return [
            'title' => $title,
            'content' => $body ? $dom->saveHTML($body) : $html
        ];
    }
}
