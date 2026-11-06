<?php
namespace RetroWEB;

final class ForwardProxyQuota
{
    private \SQLite3 $db;
    private string $secret;

    public function __construct(string $path, string $secret)
    {
        $this->secret = $secret;
        $this->db = new \SQLite3($path);
        $this->db->busyTimeout(5000);
        $this->db->exec('PRAGMA journal_mode=WAL');
        $this->db->exec('CREATE TABLE IF NOT EXISTS usage (scope TEXT NOT NULL, identity TEXT NOT NULL, bytes INTEGER NOT NULL DEFAULT 0, requests INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(scope, identity))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS alerts (alert_key TEXT PRIMARY KEY, created_at INTEGER NOT NULL)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS rate_windows (identity TEXT NOT NULL, bucket INTEGER NOT NULL, requests INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(identity,bucket))');
        $this->db->exec('CREATE TABLE IF NOT EXISTS abuse (identity TEXT PRIMARY KEY, failures INTEGER NOT NULL DEFAULT 0, window_start INTEGER NOT NULL, blocked_until INTEGER NOT NULL DEFAULT 0)');
        $this->db->exec('CREATE TABLE IF NOT EXISTS proxy_counters (counter_key TEXT PRIMARY KEY, value INTEGER NOT NULL DEFAULT 0)');
    }

    public function check(string $ip): ?string
    {
        $day = gmdate('Y-m-d');
        $month = gmdate('Y-m');
        if ($this->bytes('month', $month) >= FORWARD_PROXY_MONTHLY_BYTES) return 'Monthly proxy traffic limit reached';
        if ($this->bytes('day', $day) >= FORWARD_PROXY_DAILY_BYTES) return 'Daily proxy traffic limit reached';
        if ($this->bytes('ip-day', $day . ':' . $this->fingerprint($ip)) >= FORWARD_PROXY_IP_DAILY_BYTES) return 'Daily client traffic limit reached';
        return null;
    }

    public function record(string $ip, int $bytes): array
    {
        $bytes = max(0, $bytes);
        $day = gmdate('Y-m-d');
        $month = gmdate('Y-m');
        $this->db->exec('BEGIN IMMEDIATE');
        try {
            $this->increment('month', $month, $bytes);
            $this->increment('day', $day, $bytes);
            $this->increment('ip-day', $day . ':' . $this->fingerprint($ip), $bytes);
            $this->db->exec('COMMIT');
        } catch (\Throwable $error) {
            $this->db->exec('ROLLBACK');
            throw $error;
        }
        $monthly = $this->bytes('month', $month);
        $newAlerts = [];
        foreach ([5_000_000_000_000,8_000_000_000_000,9_000_000_000_000] as $threshold) {
            if ($monthly < $threshold) continue;
            $key = $month . ':' . $threshold;
            $statement = $this->db->prepare('INSERT OR IGNORE INTO alerts(alert_key, created_at) VALUES(:key, :created)');
            $statement->bindValue(':key', $key, SQLITE3_TEXT);
            $statement->bindValue(':created', time(), SQLITE3_INTEGER);
            $statement->execute();
            if ($this->db->changes() > 0) $newAlerts[] = $threshold;
        }
        return $newAlerts;
    }

    public function consumeRequest(string $ip, int $limit = 30, int $window = 60): bool
    {
        $identity = $this->fingerprint($ip);
        $bucket = intdiv(time(), $window);
        $statement = $this->db->prepare('INSERT INTO rate_windows(identity,bucket,requests) VALUES(:identity,:bucket,1) ON CONFLICT(identity,bucket) DO UPDATE SET requests=requests+1');
        $statement->bindValue(':identity',$identity,SQLITE3_TEXT); $statement->bindValue(':bucket',$bucket,SQLITE3_INTEGER); $statement->execute();
        $query = $this->db->prepare('SELECT requests FROM rate_windows WHERE identity=:identity AND bucket=:bucket');
        $query->bindValue(':identity',$identity,SQLITE3_TEXT); $query->bindValue(':bucket',$bucket,SQLITE3_INTEGER);
        $count = (int)($query->execute()->fetchArray(SQLITE3_ASSOC)['requests'] ?? 0);
        if (random_int(1,100) === 1) $this->db->exec('DELETE FROM rate_windows WHERE bucket < ' . ($bucket - 2));
        return $count <= $limit;
    }

    public function isBlocked(string $ip): bool
    {
        $statement=$this->db->prepare('SELECT blocked_until FROM abuse WHERE identity=:identity');
        $statement->bindValue(':identity',$this->fingerprint($ip),SQLITE3_TEXT);
        return (int)($statement->execute()->fetchArray(SQLITE3_ASSOC)['blocked_until']??0)>time();
    }

    public function recordFailure(string $ip): void
    {
        $identity=$this->fingerprint($ip); $now=time();
        $statement=$this->db->prepare('SELECT failures,window_start FROM abuse WHERE identity=:identity');
        $statement->bindValue(':identity',$identity,SQLITE3_TEXT); $row=$statement->execute()->fetchArray(SQLITE3_ASSOC);
        $failures=(!$row || (int)$row['window_start']<$now-600)?1:(int)$row['failures']+1;
        $start=(!$row || (int)$row['window_start']<$now-600)?$now:(int)$row['window_start'];
        $blocked=$failures>=10?$now+900:0;
        $upsert=$this->db->prepare('INSERT INTO abuse(identity,failures,window_start,blocked_until) VALUES(:identity,:failures,:start,:blocked) ON CONFLICT(identity) DO UPDATE SET failures=:failures,window_start=:start,blocked_until=:blocked');
        $upsert->bindValue(':identity',$identity,SQLITE3_TEXT);$upsert->bindValue(':failures',$failures,SQLITE3_INTEGER);
        $upsert->bindValue(':start',$start,SQLITE3_INTEGER);$upsert->bindValue(':blocked',$blocked,SQLITE3_INTEGER);$upsert->execute();
        $this->incrementCounter('rejected_requests');
    }

    public function incrementCounter(string $key): void
    {
        $statement=$this->db->prepare('INSERT INTO proxy_counters(counter_key,value) VALUES(:key,1) ON CONFLICT(counter_key) DO UPDATE SET value=value+1');
        $statement->bindValue(':key',$key,SQLITE3_TEXT);$statement->execute();
    }

    public function totals(): array
    {
        return ['day'=>$this->bytes('day', gmdate('Y-m-d')), 'month'=>$this->bytes('month', gmdate('Y-m')),
            'requests'=>$this->requests('month',gmdate('Y-m')),'rejected'=>$this->counter('rejected_requests')];
    }

    private function fingerprint(string $ip): string { return hash_hmac('sha256', $ip, $this->secret); }
    private function bytes(string $scope, string $identity): int
    {
        $statement = $this->db->prepare('SELECT bytes FROM usage WHERE scope=:scope AND identity=:identity');
        $statement->bindValue(':scope', $scope, SQLITE3_TEXT);
        $statement->bindValue(':identity', $identity, SQLITE3_TEXT);
        $row = $statement->execute()->fetchArray(SQLITE3_ASSOC);
        return (int)($row['bytes'] ?? 0);
    }
    private function requests(string $scope,string $identity): int
    {
        $statement=$this->db->prepare('SELECT requests FROM usage WHERE scope=:scope AND identity=:identity');
        $statement->bindValue(':scope',$scope,SQLITE3_TEXT);$statement->bindValue(':identity',$identity,SQLITE3_TEXT);
        return (int)($statement->execute()->fetchArray(SQLITE3_ASSOC)['requests']??0);
    }
    private function counter(string $key): int
    {
        $statement=$this->db->prepare('SELECT value FROM proxy_counters WHERE counter_key=:key');$statement->bindValue(':key',$key,SQLITE3_TEXT);
        return (int)($statement->execute()->fetchArray(SQLITE3_ASSOC)['value']??0);
    }
    private function increment(string $scope, string $identity, int $bytes): void
    {
        $statement = $this->db->prepare('INSERT INTO usage(scope, identity, bytes, requests) VALUES(:scope,:identity,:bytes,1) ON CONFLICT(scope,identity) DO UPDATE SET bytes=bytes+:bytes, requests=requests+1');
        $statement->bindValue(':scope', $scope, SQLITE3_TEXT);
        $statement->bindValue(':identity', $identity, SQLITE3_TEXT);
        $statement->bindValue(':bytes', $bytes, SQLITE3_INTEGER);
        $statement->execute();
    }
}
