<?php
/**
 * RetroWEB - Homepage met zoekfunctionaliteit
 */

require_once __DIR__ . '/config.php';

// Initialiseer error handling
initErrorHandling();

// Stel security headers in
setSecurityHeaders();
setHtmlNoCacheHeaders();

// Check request size
if (!checkRequestSize()) {
    sendHttp10Response(413);
    $errorHtml = "<html><head><title>Request Too Large</title></head><body>\n";
    $errorHtml .= "<h1>413 Request Entity Too Large</h1>\n";
    $errorHtml .= "<p>Request size exceeds maximum allowed size.</p>\n";
    $errorHtml .= "</body></html>\n";
    setHttp10Headers(strlen($errorHtml));
    echo $errorHtml;
    exit;
}

$imageMode = getImageMode();
$activeSettings = getUserSettings();
rememberUserSettings($activeSettings);
$basePath = getBasePath();
$baseUrl = getBaseUrl();

// Track bezoeker en pageview
trackVisitor();

$searchQuery = isset($_GET['q']) ? trim($_GET['q']) : '';
$searchResults = [];

// Check of input een URL is - zo ja, redirect direct naar proxy
if (!empty($searchQuery)) {
    // Check of het een URL lijkt te zijn (soepelere validatie voor HTTP/1.0 browsers)
    $isUrl = false;
    if (preg_match('/^https?:\/\//', $searchQuery)) {
        $isUrl = true;
    } elseif (preg_match('/^[a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,}/', $searchQuery)) {
        // Lijkt op een domain (bijv. example.com)
        $isUrl = true;
        $searchQuery = 'https://' . $searchQuery;
    }
    
    // Soepelere URL validatie: gebruik regex in plaats van filter_var
    // filter_var kan te strikt zijn voor HTTP/1.0 browsers
    if ($isUrl) {
        // Basis URL validatie via regex (soepeler dan filter_var)
        if (preg_match('/^https?:\/\/[a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-zA-Z]{2,}/', $searchQuery)) {
            // Redirect naar proxy
            sendHttp10Response(302);
            header('Location: ' . buildRetroWebUrl('proxy.php', \RetroWEB\UserSettings::query($activeSettings, ['url'=>$searchQuery])));
            exit;
        }
    }
}

// Als er een zoekopdracht is, voer DuckDuckGo search uit via geïsoleerde functie
if (!empty($searchQuery)) {
    // Valideer search query
    if (!validateSearchQuery($searchQuery)) {
        sendHttp10Response(400);
        $errorHtml = "<html><head><title>Invalid Search Query</title></head><body>\n";
        $errorHtml .= renderNavigation($imageMode);
        $errorHtml .= "<h1>Invalid Search Query</h1>\n";
        $errorHtml .= "<p>The search query contains invalid characters or is too long.</p>\n";
        $errorHtml .= "</body></html>\n";
        setHttp10Headers(strlen($errorHtml));
        echo $errorHtml;
        exit;
    }
    
    // Rate limiting voor search requests
    if (!checkRateLimit()) {
        exit; // checkRateLimit() heeft al error response gestuurd
    }
    
    require_once __DIR__ . '/search_engine.php';
    $searchResults = performSearch($searchQuery);
}

// Output HTML
sendHttp10Response(200);
$htmlOutput = "<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 2.0//EN\">\n";
$htmlOutput .= "<html>\n<head>\n";
$htmlOutput .= "<title>RetroWEB - Web Proxy</title>\n";
$htmlOutput .= "</head>\n<body>\n";

$htmlOutput .= renderNavigation($imageMode);

$htmlOutput .= "<h1>RetroWEB</h1>\n";
$htmlOutput .= "<p>Web Proxy for old browsers</p>\n";

// Search form (also works as URL input)
$htmlOutput .= "<form method=\"get\" action=\"" . htmlspecialchars($baseUrl . '/index.php') . "\">\n";
foreach (\RetroWEB\UserSettings::query($activeSettings) as $name=>$value) $htmlOutput .= '<input type="hidden" name="'.htmlspecialchars($name).'" value="'.htmlspecialchars($value).'">' . "\n";
$htmlOutput .= "<input type=\"text\" name=\"q\" size=\"50\" value=\"" . htmlspecialchars($searchQuery) . "\">\n";
$htmlOutput .= "<input type=\"submit\" value=\"Search / Go\">\n";
$htmlOutput .= "</form>\n";
$htmlOutput .= "<p></p>\n";
$htmlOutput .= "<hr>\n";

// Display search results
if (!empty($searchQuery)) {
    if (!empty($searchResults)) {
        $htmlOutput .= "<h2>Search results for: " . htmlspecialchars($searchQuery) . "</h2>\n";
        $htmlOutput .= "<ol>\n";
        
        foreach ($searchResults as $result) {
            $proxyUrl = buildRetroWebUrl('proxy.php', \RetroWEB\UserSettings::query($activeSettings, ['url'=>$result['url']]));
            
            $htmlOutput .= "<li>\n";
            $htmlOutput .= "<p><b><a href=\"" . htmlspecialchars($proxyUrl) . "\">" . htmlspecialchars($result['title']) . "</a></b></p>\n";
            $htmlOutput .= "<p>" . htmlspecialchars($result['url']) . "</p>\n";
            if (!empty($result['description'])) {
                $htmlOutput .= "<p>" . htmlspecialchars($result['description']) . "</p>\n";
            }
            $htmlOutput .= "</li>\n";
        }
        
        $htmlOutput .= "</ol>\n";
    } else {
        $htmlOutput .= "<p>No results found for: <b>" . htmlspecialchars($searchQuery) . "</b></p>\n";
        $htmlOutput .= "<p>Try a different search term or use the search form above to go directly to a page.</p>\n";
    }
} else {
    $htmlOutput .= "<h2>Welcome to RetroWEB</h2>\n";
    $htmlOutput .= "<p>Use the search form above to search the web, or enter a URL to view a page.</p>\n";
    $htmlOutput .= "<h3>Features:</h3>\n";
    $htmlOutput .= "<ul>\n";
    $htmlOutput .= "<li>Search the web via DuckDuckGo</li>\n";
    $htmlOutput .= "<li>View modern web pages in simplified HTML 2.0 format</li>\n";
    $htmlOutput .= "<li>Toggle between image links and inline images</li>\n";
    $htmlOutput .= "<li>Automatic image conversion to (small)gif files for better compatibility</li>\n";
    $htmlOutput .= "</ul>\n";
}

$htmlOutput .= "<hr>\n";
$htmlOutput .= '<p><a href="' . htmlspecialchars($baseUrl . '/stats.php') . '">Public statistics</a></p>' . "\n";
// Email obfuscatie voor spam bot bescherming (HTML entities)
// bjorn@heirman.nl wordt: b&#106;orn&#64;heirman&#46;nl
$htmlOutput .= "<p>Made by <a href=\"mailto:b&#106;orn&#64;heirman&#46;nl\">Bj&#246;rn Heirman</a></p>\n";

$htmlOutput .= "</body>\n</html>\n";

setHttp10Headers(strlen($htmlOutput));
echo $htmlOutput;
