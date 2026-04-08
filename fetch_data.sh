#!/bin/bash
# Fetch real 1-minute price data from CryptoCompare using curl
# CryptoCompare gives 2000 candles per request = ~33 hours
# For 7 days (168h) we need ~5 requests per asset

set -e
mkdir -p data/cache

SYMBOLS=("BTC" "ETH" "SOL" "XRP")
HOURS=168  # 7 days
MINUTES=$((HOURS * 60))
LIMIT=2000

for SYM in "${SYMBOLS[@]}"; do
    echo "=== Fetching $SYM ==="
    OUTFILE="data/cache/real_${SYM}_7d.csv"
    TMPDIR=$(mktemp -d)

    END_TS=$(date +%s)
    REMAINING=$MINUTES
    CHUNK=0

    while [ $REMAINING -gt 0 ]; do
        FETCH=$(( REMAINING < LIMIT ? REMAINING : LIMIT ))
        CHUNK=$((CHUNK + 1))

        echo "  Chunk $CHUNK: fetching $FETCH minutes ending at $END_TS..."

        RESP=$(curl -s --max-time 30 \
            "https://min-api.cryptocompare.com/data/v2/histominute?fsym=${SYM}&tsym=USD&limit=${FETCH}&toTs=${END_TS}")

        # Check for error
        STATUS=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('Response',''))")
        if [ "$STATUS" != "Success" ]; then
            echo "  ERROR: $STATUS"
            break
        fi

        # Extract data to temp file — only CSV, no stderr
        echo "$RESP" | python3 -c "
import json, sys, csv
data = json.load(sys.stdin)
candles = data.get('Data', {}).get('Data', [])
writer = csv.writer(sys.stdout)
for c in candles:
    if c.get('volumefrom', 0) > 0 or c.get('open') != c.get('close'):
        writer.writerow([c['time']*1000, c['open'], c['high'], c['low'], c['close'], c.get('volumefrom',0)])
" > "$TMPDIR/chunk_${CHUNK}.csv"

        COUNT=$(wc -l < "$TMPDIR/chunk_${CHUNK}.csv")
        echo "  Got $COUNT candles"

        # Get earliest timestamp for next chunk
        EARLIEST=$(head -1 "$TMPDIR/chunk_${CHUNK}.csv" | cut -d, -f1)
        if [ -z "$EARLIEST" ]; then
            echo "  No data in chunk, stopping"
            break
        fi
        END_TS=$(( EARLIEST / 1000 - 1 ))
        REMAINING=$((REMAINING - FETCH))

        sleep 0.5
    done

    # Combine chunks into single CSV (with header, sorted by time, deduped)
    echo "timestamp,open,high,low,close,volume" > "$OUTFILE"
    cat "$TMPDIR"/chunk_*.csv | sort -t, -k1 -n | uniq >> "$OUTFILE"

    TOTAL=$(wc -l < "$OUTFILE")
    TOTAL=$((TOTAL - 1))
    echo "  $SYM: saved $TOTAL candles to $OUTFILE"

    rm -rf "$TMPDIR"
    sleep 1
done

echo ""
echo "=== Done ==="
for f in data/cache/real_*_7d.csv; do
    LINES=$(wc -l < "$f")
    echo "  $f: $((LINES-1)) candles"
done
