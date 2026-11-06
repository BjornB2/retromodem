<?php
/**
 * RetroWEB - Cleanup script voor visitor tracking
 * Verwijdert oude visitor entries uit de database
 * 
 * Dit script moet via cron worden aangeroepen (bijv. elk uur):
 * 0 * * * * cd /path/to/retroweb && /usr/bin/php cleanup_visitors.php >> /var/log/retroweb-cleanup.log 2>&1
 */

// Exit code tracking
$exitCode = 0;

try {
    require_once __DIR__ . '/config.php';
} catch (Throwable $e) {
    error_log("Config load error: " . $e->getMessage());
    exit(1);
}

// Check of visitor tracking enabled is
if (!defined('VISITOR_TRACKING_ENABLED') || !VISITOR_TRACKING_ENABLED) {
    error_log('Visitor tracking is disabled, skipping cleanup');
    exit(0);
}

try {
    $db = getStatsDatabase();
    if ($db === null) {
        error_log('Could not connect to stats database, skipping cleanup');
        exit(1);
    }
    
    $window = defined('VISITOR_TRACKING_WINDOW') ? VISITOR_TRACKING_WINDOW : 86400;
    $cutoff = time() - $window;
    
    // Verwijder entries ouder dan de window
    $stmt = $db->prepare('DELETE FROM visitor_ips WHERE first_seen < ?');
    $stmt->bindValue(1, $cutoff, SQLITE3_INTEGER);
    $stmt->execute();
    
    $deleted = $db->changes();
    
    if ($deleted > 0) {
        error_log("Cleanup: removed $deleted old visitor entries (older than " . ($window / 3600) . " hours)");
    } else {
        error_log("Cleanup: no old entries to remove");
    }
    
    // Optioneel: VACUUM database om ruimte te besparen (kan traag zijn bij grote databases)
    // $db->exec('VACUUM');
    
    $db->close();
    
    exit(0);
    
} catch (Exception $e) {
    error_log('Cleanup error: ' . $e->getMessage());
    error_log('Stack trace: ' . $e->getTraceAsString());
    exit(1);
} catch (Throwable $e) {
    error_log('Cleanup fatal error: ' . $e->getMessage());
    error_log('Stack trace: ' . $e->getTraceAsString());
    exit(1);
}
