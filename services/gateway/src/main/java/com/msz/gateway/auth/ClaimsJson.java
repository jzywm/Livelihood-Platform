package com.msz.gateway.auth;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * JWT payload 最小 JSON 解析(不引 JSON 库,同 acc 手写口径)。
 * 支持 null / Boolean / Number(整数→Long,小数→Double)/ String / Array / Object。
 */
public final class ClaimsJson {

    private ClaimsJson() {
    }

    public static Map<String, Object> parseObject(String json) {
        Parser parser = new Parser(json);
        Object value = parser.parseValue();
        parser.skipWhitespace();
        if (!parser.atEnd()) {
            throw new IllegalArgumentException("JSON 尾部多余内容");
        }
        if (!(value instanceof Map<?, ?> map)) {
            throw new IllegalArgumentException("顶层不是 JSON 对象");
        }
        Map<String, Object> result = new LinkedHashMap<>();
        map.forEach((k, v) -> result.put(String.valueOf(k), v));
        return result;
    }

    private static final class Parser {

        private final String s;
        private int i;

        Parser(String s) {
            this.s = s;
        }

        boolean atEnd() {
            return i >= s.length();
        }

        void skipWhitespace() {
            while (!atEnd() && Character.isWhitespace(s.charAt(i))) {
                i++;
            }
        }

        char peek() {
            if (atEnd()) {
                throw new IllegalArgumentException("JSON 意外结束");
            }
            return s.charAt(i);
        }

        char next() {
            char c = peek();
            i++;
            return c;
        }

        void expect(char c) {
            if (next() != c) {
                throw new IllegalArgumentException("JSON 语法错误,期望 '" + c + "'");
            }
        }

        Object parseValue() {
            skipWhitespace();
            char c = peek();
            return switch (c) {
                case '{' -> parseObject();
                case '[' -> parseArray();
                case '"' -> {
                    next(); // 消费开引号,parseString 读取内容至闭引号
                    yield parseString();
                }
                case 't' -> parseWord("true", Boolean.TRUE);
                case 'f' -> parseWord("false", Boolean.FALSE);
                case 'n' -> parseWord("null", null);
                default -> parseNumber();
            };
        }

        Map<String, Object> parseObject() {
            expect('{');
            Map<String, Object> map = new LinkedHashMap<>();
            skipWhitespace();
            if (peek() == '}') {
                next();
                return map;
            }
            while (true) {
                skipWhitespace();
                if (next() != '"') {
                    throw new IllegalArgumentException("JSON 对象键必须是字符串");
                }
                String key = parseString();
                skipWhitespace();
                expect(':');
                map.put(key, parseValue());
                skipWhitespace();
                char c = next();
                if (c == '}') {
                    return map;
                }
                if (c != ',') {
                    throw new IllegalArgumentException("JSON 对象缺少逗号分隔");
                }
            }
        }

        List<Object> parseArray() {
            expect('[');
            List<Object> list = new ArrayList<>();
            skipWhitespace();
            if (peek() == ']') {
                next();
                return list;
            }
            while (true) {
                list.add(parseValue());
                skipWhitespace();
                char c = next();
                if (c == ']') {
                    return list;
                }
                if (c != ',') {
                    throw new IllegalArgumentException("JSON 数组缺少逗号分隔");
                }
            }
        }

        String parseString() {
            StringBuilder sb = new StringBuilder();
            while (true) {
                char c = next();
                if (c == '"') {
                    return sb.toString();
                }
                if (c == '\\') {
                    char esc = next();
                    switch (esc) {
                        case '"' -> sb.append('"');
                        case '\\' -> sb.append('\\');
                        case '/' -> sb.append('/');
                        case 'b' -> sb.append('\b');
                        case 'f' -> sb.append('\f');
                        case 'n' -> sb.append('\n');
                        case 'r' -> sb.append('\r');
                        case 't' -> sb.append('\t');
                        case 'u' -> {
                            if (i + 4 > s.length()) {
                                throw new IllegalArgumentException("JSON \\u 转义不完整");
                            }
                            String hex = s.substring(i, i + 4);
                            sb.append((char) Integer.parseInt(hex, 16));
                            i += 4;
                        }
                        default -> throw new IllegalArgumentException("JSON 非法转义 \\" + esc);
                    }
                } else {
                    sb.append(c);
                }
            }
        }

        Object parseWord(String word, Object value) {
            if (s.startsWith(word, i)) {
                i += word.length();
                return value;
            }
            throw new IllegalArgumentException("JSON 非法字面量");
        }

        Object parseNumber() {
            int start = i;
            if (peek() == '-') {
                i++;
            }
            while (!atEnd() && Character.isDigit(s.charAt(i))) {
                i++;
            }
            boolean floating = false;
            if (!atEnd() && s.charAt(i) == '.') {
                floating = true;
                i++;
                while (!atEnd() && Character.isDigit(s.charAt(i))) {
                    i++;
                }
            }
            if (!atEnd() && (s.charAt(i) == 'e' || s.charAt(i) == 'E')) {
                floating = true;
                i++;
                if (!atEnd() && (s.charAt(i) == '+' || s.charAt(i) == '-')) {
                    i++;
                }
                while (!atEnd() && Character.isDigit(s.charAt(i))) {
                    i++;
                }
            }
            String text = s.substring(start, i);
            if (text.isEmpty() || "-".equals(text)) {
                throw new IllegalArgumentException("JSON 非法数字");
            }
            try {
                // 注意:不可用三元表达式(cond ? Double.valueOf : Long.valueOf)——
                // 两者都可拆箱为数值类型,JLS 15.25 会做二进制数值提升(double),整数会被吞成 Double。
                if (floating) {
                    return Double.valueOf(text);
                }
                return Long.valueOf(text);
            } catch (NumberFormatException e) {
                return Double.valueOf(text);
            }
        }
    }
}
