<?php
/**
 * RetroWEB - Geïsoleerde Search Engine functionaliteit
 * Deze module is volledig gescheiden van de rest van de applicatie
 * en gebruikt cURL voor DuckDuckGo/Startpage search
 */

/**
 * Voer een zoekopdracht uit via DuckDuckGo (met Startpage fallback)
 * @param string $query Zoekterm
 * @return array Array met search results ['title' => string, 'url' => string, 'description' => string]
 */
function performSearch($query) {
    // Valideer search query
    if (function_exists('validateSearchQuery') && !validateSearchQuery($query)) {
        return []; // Return empty results als query invalid is
    }
    
    // Rate limiting (wordt al gecheckt in index.php, maar extra check hier voor directe calls)
    if (function_exists('checkRateLimit') && !checkRateLimit()) {
        return []; // Return empty results als rate limit overschreden
    }
    
    $searchResults = [];
    $html = false;
    $searchEngine = 'duckduckgo';
    
    // Gebruik cURL voor betere controle over headers en cookies
    $ch = curl_init();
    
    // DuckDuckGo HTML endpoint
    $searchUrl = 'https://html.duckduckgo.com/html/?q=' . urlencode($query);
    
    // Cookie bestand voor sessie behoud
    $cookieFile = sys_get_temp_dir() . '/ddg_cookies_' . md5(__DIR__) . '.txt';
    
    // Realistische browser headers (geïsoleerd - heeft geen invloed op rest van app)
    $headers = [
        'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language: en-US,en;q=0.9',
        'Accept-Encoding: gzip, deflate', // Geen "br" - libcurl ondersteunt dit niet standaard
        'Referer: https://duckduckgo.com/',
        'Connection: keep-alive',
        'Upgrade-Insecure-Requests: 1',
        'Sec-Fetch-Dest: document',
        'Sec-Fetch-Mode: navigate',
        'Sec-Fetch-Site: same-origin',
        'Cache-Control: max-age=0'
    ];
    
    curl_setopt_array($ch, [
        CURLOPT_URL => $searchUrl,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_FOLLOWLOCATION => true,
        CURLOPT_MAXREDIRS => 5,
        CURLOPT_HTTPHEADER => $headers,
        CURLOPT_COOKIEJAR => $cookieFile,  // Sla cookies op
        CURLOPT_COOKIEFILE => $cookieFile, // Gebruik cookies
        CURLOPT_TIMEOUT => 30,
        CURLOPT_SSL_VERIFYPEER => true,
        CURLOPT_ENCODING => 'gzip, deflate', // Alleen gzip en deflate (geen br/Brotli)
    ]);
    
    $html = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $curlError = curl_error($ch);
    curl_close($ch);
    
    // Check of DuckDuckGo een CAPTCHA challenge teruggeeft
    if ($html !== false && ($httpCode == 202 || strpos($html, 'anomaly-modal') !== false || strpos($html, 'Unfortunately, bots use DuckDuckGo') !== false)) {
        // DuckDuckGo blokkeert als bot, probeer Startpage
        $searchEngine = 'startpage';
        $searchUrl = 'https://www.startpage.com/sp/search?query=' . urlencode($query) . '&language=english';
        
        $ch = curl_init();
        curl_setopt_array($ch, [
            CURLOPT_URL => $searchUrl,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_FOLLOWLOCATION => true,
            CURLOPT_MAXREDIRS => 5,
            CURLOPT_HTTPHEADER => $headers,
            CURLOPT_TIMEOUT => 30,
            CURLOPT_SSL_VERIFYPEER => true,
            CURLOPT_ENCODING => 'gzip, deflate',
        ]);
        
        $html = curl_exec($ch);
        curl_close($ch);
    }
    
    if ($html === false) {
        return $searchResults; // Lege array als request faalt
    }
    
    // Parse search resultaten
    $dom = new DOMDocument();
    @$dom->loadHTML('<?xml encoding="UTF-8">' . $html);
    $xpath = new DOMXPath($dom);
    
    if ($searchEngine === 'startpage') {
        // Startpage parsing
        $resultNodes = $xpath->query('//div[contains(@class, "w-gl__result")] | //div[contains(@class, "result")] | //a[contains(@class, "result")]');
        
        if ($resultNodes->length === 0) {
            $resultNodes = $xpath->query('//a[contains(@href, "/sp/click")] | //a[contains(@class, "result-link")]');
        }
    } else {
        // DuckDuckGo parsing
        $resultNodes = $xpath->query('//div[contains(@class, "result")] | //div[contains(@class, "web-result")] | //div[contains(@class, "links_main")]//div[contains(@class, "result")]');
        
        if ($resultNodes->length === 0) {
            $resultNodes = $xpath->query('//a[contains(@class, "result__a")] | //a[contains(@class, "result__url")] | //a[contains(@class, "result-link")]');
        }
        
        if ($resultNodes->length === 0) {
            $resultNodes = $xpath->query('//a[@class="result__a"]');
        }
    }
    
    foreach ($resultNodes as $node) {
        $title = '';
        $url = '';
        $description = '';
        
        // Zoek naar link
        $linkNode = $xpath->query('.//a[@class="result__a"] | .//a[contains(@class, "result__url")] | .//a', $node)->item(0);
        if (!$linkNode) {
            $linkNode = $node->nodeName === 'a' ? $node : null;
        }
        
        if ($linkNode) {
            $url = $linkNode->getAttribute('href');
            $title = trim($linkNode->textContent);
            
            // Handle verschillende URL formats
            if ($searchEngine === 'startpage') {
                // Startpage gebruikt /sp/click redirect links
                if (strpos($url, '/sp/click') === 0) {
                    if (preg_match('/url=([^&]+)/', $url, $matches)) {
                        $url = urldecode($matches[1]);
                    } elseif (preg_match('/\/sp\/click\?url=([^&]+)/', $url, $matches)) {
                        $url = urldecode($matches[1]);
                    }
                }
            } else {
                // DuckDuckGo redirect handling
                // Handle protocol-relative URLs (//duckduckgo.com/l/?uddg=...)
                if (strpos($url, '//duckduckgo.com/l/') !== false || 
                    strpos($url, '/l/?') === 0 || 
                    strpos($url, '/l/') === 0 ||
                    strpos($url, '?uddg=') !== false) {
                    // Try multiple patterns
                    if (preg_match('/[?&]uddg=([^&]+)/', $url, $matches)) {
                        $url = urldecode($matches[1]);
                    } elseif (preg_match('/uddg%3D([^&]+)/', $url, $matches)) {
                        $url = urldecode(urldecode($matches[1]));
                    } elseif (preg_match('/uddg=([^&]+)/', html_entity_decode($url), $matches)) {
                        $url = urldecode($matches[1]);
                    }
                }
            }
            
            // Zoek naar beschrijving
            if ($searchEngine === 'startpage') {
                $descNode = $xpath->query('.//p[contains(@class, "w-gl__description")] | .//div[contains(@class, "description")] | .//span[contains(@class, "snippet")]', $node)->item(0);
            } else {
                $descNode = $xpath->query('.//a[@class="result__snippet"] | .//div[contains(@class, "result__snippet")] | .//span[contains(@class, "result__snippet")] | .//div[contains(@class, "snippet")]', $node)->item(0);
                if (!$descNode) {
                    $descNode = $xpath->query('.//div[contains(@class, "result__body")]//div[contains(@class, "snippet")]', $node)->item(0);
                }
            }
            if ($descNode) {
                $description = trim($descNode->textContent);
                $description = preg_replace('/\s+/', ' ', $description);
            }
        }
        
        if (!empty($title) && !empty($url)) {
            // Valideer URL
            if (!filter_var($url, FILTER_VALIDATE_URL)) {
                if (!preg_match('/^https?:\/\//', $url)) {
                    $url = 'https://' . $url;
                }
            }
            
            if (filter_var($url, FILTER_VALIDATE_URL)) {
                $searchResults[] = [
                    'title' => $title,
                    'url' => $url,
                    'description' => $description
                ];
            }
        }
    }
    
    // Als geen resultaten gevonden met DOM parsing, probeer regex fallback
    if (empty($searchResults)) {
        if ($searchEngine === 'startpage') {
            // Startpage regex fallback
            preg_match_all('/<a[^>]+href="(\/sp\/click[^"]+)"[^>]*>(.*?)<\/a>/is', $html, $matches, PREG_SET_ORDER);
            
            if (empty($matches)) {
                preg_match_all('/<a[^>]+href="([^"]+)"[^>]*class="[^"]*result[^"]*"[^>]*>(.*?)<\/a>/is', $html, $matches, PREG_SET_ORDER);
            }
            
            foreach ($matches as $match) {
                $url = html_entity_decode($match[1]);
                $title = trim(strip_tags($match[2]));
                
                if (strpos($url, '/sp/click') === 0) {
                    if (preg_match('/url=([^&]+)/', $url, $urlMatch)) {
                        $url = urldecode($urlMatch[1]);
                    } elseif (preg_match('/\/sp\/click\?url=([^&]+)/', $url, $urlMatch)) {
                        $url = urldecode($urlMatch[1]);
                    }
                }
                
                if (empty($url) || $url === '/') {
                    continue;
                }
                
                if (!filter_var($url, FILTER_VALIDATE_URL)) {
                    if (!preg_match('/^https?:\/\//', $url)) {
                        $url = 'https://' . $url;
                    }
                }
                
                if (!empty($title) && filter_var($url, FILTER_VALIDATE_URL)) {
                    $searchResults[] = [
                        'title' => $title,
                        'url' => $url,
                        'description' => ''
                    ];
                }
            }
        } else {
            // DuckDuckGo regex fallback
            preg_match_all('/<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)<\/a>/is', $html, $matches, PREG_SET_ORDER);
            
            if (empty($matches)) {
                preg_match_all('/<a[^>]+href="([^"]+)"[^>]*class="[^"]*result[^"]*"[^>]*>(.*?)<\/a>/is', $html, $matches, PREG_SET_ORDER);
            }
            
            if (empty($matches)) {
                preg_match_all('/<a[^>]+href="(\/l\/[^"]+)"[^>]*>(.*?)<\/a>/is', $html, $matches, PREG_SET_ORDER);
            }
            
            foreach ($matches as $match) {
                $url = html_entity_decode($match[1]);
                $title = trim(strip_tags($match[2]));
                
                // DuckDuckGo redirect handling
                if (strpos($url, '//duckduckgo.com/l/') !== false || 
                    strpos($url, '/l/?') === 0 || 
                    strpos($url, '/l/') === 0 ||
                    strpos($url, '?uddg=') !== false) {
                    if (preg_match('/[?&]uddg=([^&]+)/', $url, $urlMatch)) {
                        $url = urldecode($urlMatch[1]);
                    } elseif (preg_match('/uddg%3D([^&]+)/', $url, $urlMatch)) {
                        $url = urldecode(urldecode($urlMatch[1]));
                    } else {
                        if (strpos($url, '//') === 0) {
                            $url = 'https:' . $url;
                        }
                        $parts = parse_url($url);
                        if (isset($parts['query'])) {
                            parse_str($parts['query'], $params);
                            if (isset($params['uddg'])) {
                                $url = urldecode($params['uddg']);
                            }
                        }
                    }
                }
                
                if (empty($url) || $url === '/') {
                    continue;
                }
                
                if (!filter_var($url, FILTER_VALIDATE_URL)) {
                    if (!preg_match('/^https?:\/\//', $url)) {
                        $url = 'https://' . $url;
                    }
                }
                
                if (!empty($title) && filter_var($url, FILTER_VALIDATE_URL)) {
                    $searchResults[] = [
                        'title' => $title,
                        'url' => $url,
                        'description' => ''
                    ];
                }
            }
        }
    }
    
    // Verwijder duplicaten op basis van URL
    $uniqueResults = [];
    $seenUrls = [];
    foreach ($searchResults as $result) {
        $urlKey = strtolower(trim($result['url']));
        // Normaliseer URL (verwijder trailing slash en fragment)
        $urlKey = rtrim($urlKey, '/');
        $urlParts = parse_url($urlKey);
        if (isset($urlParts['fragment'])) {
            $urlKey = str_replace('#' . $urlParts['fragment'], '', $urlKey);
        }
        
        if (!isset($seenUrls[$urlKey])) {
            $seenUrls[$urlKey] = true;
            $uniqueResults[] = $result;
        }
    }
    
    return $uniqueResults;
}
