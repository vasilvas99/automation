#!/bin/bash

if [ -z "$EGN" ]; then
    echo "EGN is not set"
    exit 1
fi

if [ -z "$CAR_NO" ]; then
    echo "CAR_NO is not set"
    exit 1
fi

MVR_ENDPOINT="https://e-uslugi.mvr.bg/api/Obligations/AND?obligatedPersonType=1&additinalDataForObligatedPersonType=3&mode=1&obligedPersonIdent=${EGN}&foreignVehicleNumber=${CAR_NO}"

response=$(curl -s "${MVR_ENDPOINT}")

if ! echo "$response" | jq empty >/dev/null 2>&1; then
    echo "Parsing error!"
    exit 1
fi

result=$(echo "$response" | jq 'all(.obligationsData[]; .errorNoDataFound == false and .errorReadingData == false)')

if [ "$result" != "true" ]; then
    echo "Error in response"
    exit 1
fi

obligations_empty=$(echo "$response" | jq 'all(.obligationsData[]; .obligations | length == 0)')

echo "Проверка за глоби в КАТ за ${CAR_NO} на $(date +'%Y-%m-%d %H:%M:%S')"
if [ "$obligations_empty" == "true" ]; then
    echo "Проверката за глоби в КАТ е успешна. Няма намерени глоби:"
    echo ""
    exit 0
else
    echo "Проверката за глоби в КАТ е успешна. Има намерени глоби:"
    echo ""
    echo "$response" | jq -r '.obligationsData[].obligations[]'
    echo "За повече информация: https://e-uslugi.mvr.bg/services/obligations"
    exit 0
fi
