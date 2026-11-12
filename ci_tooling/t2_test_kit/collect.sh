#!/bin/bash
# collect.sh <testo-pavadinimas>
# Surenka T2 testo rezultatus i faila darbalaukyje ir pasako santrauka.
# Pvz.: bash collect.sh A    arba    bash collect.sh B0

LABEL="${1:-be-pavadinimo}"
OUT="$HOME/Desktop/T2-testas-$LABEL.txt"

{
    echo "=== T2 testas: $LABEL"
    echo "Data: $(date)"
    sw_vers
    echo
    echo "=== Bootinimo kelias"
    OCV=$(nvram 4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102:opencore-version 2>/dev/null | awk '{print $2}')
    if [ -n "$OCV" ]; then echo "Per OpenCore: $OCV"; else echo "Natūraliai (be OpenCore)"; fi
    echo "Paleista: $(sysctl -n kern.boottime)"
    echo "Veikia: $(uptime)"
    csrutil status
    echo
    echo "=== SEP / AppleKeyStore zurnalas (siu paleidimu)"
    log show --last boot --style compact \
        --predicate 'eventMessage CONTAINS[c] "sks" OR eventMessage CONTAINS[c] "AppleKeyStore" OR eventMessage CONTAINS[c] "AppleSEP" OR eventMessage CONTAINS[c] "SEP timeout"' \
        2>/dev/null | tail -200
    echo
    echo "=== Paskutinis kernel panic (jei buvo)"
    PANIC=$(ls -t /Library/Logs/DiagnosticReports/*panic* 2>/dev/null | head -1)
    if [ -n "$PANIC" ]; then echo "$PANIC"; head -c 4000 "$PANIC"; else echo "Nera"; fi
} > "$OUT" 2>&1

STRIKES=$(grep -c "sks timeout strike" "$OUT")
TIMEOUTS=$(grep -ci "sks request timeout" "$OUT")
PATH_LINE=$(grep -m1 -E "^(Per OpenCore|Natūraliai)" "$OUT")

echo
echo "Testas $LABEL baigtas."
echo "$PATH_LINE"
echo "sks timeout strike eiluciu: $STRIKES"
echo "sks request timeout eiluciu: $TIMEOUTS"
echo "Rezultatai issaugoti: $OUT"
echo "Atsiusk si faila."
