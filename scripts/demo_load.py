"""Send a repeatable mix of normal and anomalous logs through local Fluentd."""
import argparse
import random
import time
from datetime import datetime, timezone

from fluent import sender


NORMAL_MESSAGES = [
    "INFO api-gateway request completed status=200 latency_ms=24",
    "INFO auth-service user session refreshed status=success",
    "INFO postgres connection pool healthy active=8 idle=12",
    "INFO worker job completed queue=notifications duration_ms=83",
    "INFO nginx GET /health returned 200 response_time=0.004s",
    "INFO cache hit service=catalog key=product-list hit_rate=0.94",
    "INFO payment-service transaction authorized status=success duration_ms=142",
    "INFO scheduler heartbeat received worker=3",
]

ANOMALY_MESSAGES = [
    "ERROR postgres connection timeout after 30s; pool exhausted active=50 idle=0",
    "CRITICAL disk usage reached 98%; writes failing on /var/lib/data",
    "ERROR payment-service upstream connection refused; retry limit exceeded",
    "WARN authentication rate limit exceeded source=198.51.100.42 attempts=240",
    "ERROR worker queue backlog growing rapidly pending=18432 oldest_job_age=920s",
    "FATAL kernel out of memory: killed process api-worker pid=4821",
    "ERROR TLS certificate verification failed for upstream.internal",
    "CRITICAL database replication lag is 420 seconds; replica is unhealthy",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=48, help="number of log records (default: 48)")
    parser.add_argument("--burst-size", type=int, default=16, help="records in each short burst (default: 16)")
    parser.add_argument("--burst-gap", type=float, default=2.0, help="seconds between bursts (default: 2)")
    parser.add_argument("--record-delay", type=float, default=0.025, help="seconds between records inside a burst")
    parser.add_argument("--anomaly-every", type=int, default=4, help="one obvious anomaly every N records")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=24224)
    args = parser.parse_args()
    if args.count < 1 or args.burst_size < 1 or args.anomaly_every < 1:
        parser.error("count, burst-size, and anomaly-every must be positive")

    fluent_sender = sender.FluentSender("myapp", host=args.host, port=args.port)
    sources = ["api-gateway.log", "postgresql.log", "worker.log", "auth-service.log", "kernel.log"]
    rng = random.Random(7)
    anomalies = 0
    sent = 0
    started = time.monotonic()
    print(f"Sending {args.count} demo records to Fluentd at {args.host}:{args.port}", flush=True)
    try:
        for index in range(args.count):
            is_anomaly = (index + 1) % args.anomaly_every == 0
            pool = ANOMALY_MESSAGES if is_anomaly else NORMAL_MESSAGES
            message = pool[(index // args.anomaly_every if is_anomaly else index) % len(pool)]
            source = rng.choice(sources)
            ok = fluent_sender.emit("log", {
                "file": f"demo/{source}",
                "message": f"[{datetime.now(timezone.utc).isoformat()}] {message}",
            })
            if not ok:
                error = fluent_sender.last_error
                raise RuntimeError(f"Fluentd rejected a record: {error}")
            sent += 1
            anomalies += int(is_anomaly)
            if sent % args.burst_size == 0 and sent < args.count:
                print(f"Sent burst {sent // args.burst_size}: {sent} records so far", flush=True)
                time.sleep(args.burst_gap)
            else:
                time.sleep(args.record_delay)
    finally:
        fluent_sender.close()

    elapsed = time.monotonic() - started
    print(f"Sent {sent} records ({anomalies} anomaly examples) in {elapsed:.1f}s.", flush=True)
    print("Watch the dashboard event counter and activity chart; anomaly classifications arrive as Gemini processes each entry.", flush=True)


if __name__ == "__main__":
    main()
