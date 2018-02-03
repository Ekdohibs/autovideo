#!/usr/bin/env bash

FILE="input"
if [[ $# -gt 0 ]]; then
    FILE="$1"
fi
if [ ! -f $FILE ]; then
    echo "$FILE: not found"
    exit 1
fi

OUT=out.png
if [[ $# -gt 1 ]]; then
    OUT="$2"
fi

if [[ "$(wc -l $FILE | cut -d" " -f 1)" -lt 3 ]]; then
    echo "$FILE: not long enough"
fi

SPECT=$(head -n 1 $FILE)
DATE=$(head -n 2 $FILE | tail -n 1)
DANSERS=$(tail -n +3 $FILE | sed -E ':a;N;$!ba;s/\r{0,1}\n/\\n/g')

DATEREGEX='([0-9]+ .*) ([0-9]{4})'
[[ $DATE =~ $DATEREGEX ]]
if [[ ! "$?" -eq 0 ]]; then
    echo "$FILE: invalid date"
    exit 1
fi
DAY=${BASH_REMATCH[1]}
YEAR=${BASH_REMATCH[2]}

convert rock.png -gravity North -font Sofia-Regular.otf -fill white -pointsize 84 \
    -annotate +200+200 "BdS" \
    -annotate +200+300 "$SPECT" \
    -annotate +400+500 "$DANSERS" \
    -annotate +800+200 "$DAY" -annotate +800+300 "$YEAR" \
    $OUT

