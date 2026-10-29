#!/bin/sh
# 移动端 JS 的类型检查 (checkJs). 运行: ./typecheck.sh
# tsc 默认使用 PATH 中的 tsc; 也可以指定: TSC="npx -p typescript@5 tsc" ./typecheck.sh
# web 的源码也会被一起检查 (移动端依赖它们的类型), 那些错误不在本项目范围内, 这里只报告 src/ 下的错误.
cd "$(dirname "$0")" || exit 2
TSC="${TSC:-tsc}"
OUT=$($TSC -p jsconfig.json 2>&1)
ERRORS=$(printf '%s\n' "$OUT" | grep '^src/' || true)
if [ -n "$ERRORS" ]; then
    printf '%s\n' "$ERRORS"
    echo "mobile_web: type errors found in src/"
    exit 1
fi
echo "mobile_web: no type errors in src/"
