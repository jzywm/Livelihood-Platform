package com.msz.acc.infrastructure.auth;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 极简 JSON 编解码（仅覆盖 JWT payload 与 Envelope 错误响应所需的原始类型）。
 *
 * <p>S2 不引入 JWT/JSON 库（YAGNI），auth 包内 JwtCodec（claims 序列化）与
 * AuthFilter（Envelope JSON 输出）共用此工具。仅支持：null / Boolean / Number /
 * String / Map&lt;String,Object&gt;，值均为原始类型（不嵌套对象/数组）。</p>
 *
 * <p>2026-09-15 由包内可见提升为 public：会话族记录（{@code acc:session:{familyId}} 的值）落在
 * {@code infrastructure.auth.session} 子包，需要复用同一套手写编解码——子包与父包在 Java 中不共享
 * 包级私有访问，故提升可见性而非复制一份实现。<b>刻意保持「扁平对象」限制</b>：会话族记录因此用
 * {@code rotated.<jti>} 前缀键表达「已轮换标记」映射，而不是 JSON 数组/嵌套对象
 * （见 {@code com.msz.acc.infrastructure.auth.session.FamilyRecordJson}）。</p>
 */
public final class Json {

    private Json() {
    }

    public static String toJson(Object value) {
        StringBuilder sb = new StringBuilder();
        write(sb, value);
        return sb.toString();
    }

    /** 解析扁平 JSON 对象为 Map（键为字符串，值为 String/Long/Double/Boolean/null）。 */
    public static Map<String, Object> parseObject(String json) {
        Parser p = new Parser(json);
        Object result = p.parseValue();
        p.skipWhitespace();
        if (p.hasMore()) {
            throw new IllegalArgumentException("JSON 尾部多余内容");
        }
        if (!(result instanceof Map)) {
            throw new IllegalArgumentException("JSON 顶层不是对象");
        }
        @SuppressWarnings("unchecked")
        Map<String, Object> map = (Map<String, Object>) result;
        return map;
    }

    private static void write(StringBuilder sb, Object value) {
        if (value == null) {
            sb.append("null");
        } else if (value instanceof String s) {
            writeString(sb, s);
        } else if (value instanceof Boolean b) {
            sb.append(b ? "true" : "false");
        } else if (value instanceof Number n) {
            sb.append(n.toString());
        } else if (value instanceof Map<?, ?> map) {
            sb.append('{');
            boolean first = true;
            for (Map.Entry<?, ?> e : map.entrySet()) {
                if (!first) {
                    sb.append(',');
                }
                first = false;
                writeString(sb, String.valueOf(e.getKey()));
                sb.append(':');
                write(sb, e.getValue());
            }
            sb.append('}');
        } else {
            writeString(sb, String.valueOf(value));
        }
    }

    private static void writeString(StringBuilder sb, String s) {
        sb.append('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"' -> sb.append("\\\"");
                case '\\' -> sb.append("\\\\");
                case '\n' -> sb.append("\\n");
                case '\r' -> sb.append("\\r");
                case '\t' -> sb.append("\\t");
                case '\b' -> sb.append("\\b");
                case '\f' -> sb.append("\\f");
                default -> {
                    if (c < 0x20) {
                        sb.append(String.format("\\u%04x", (int) c));
                    } else {
                        sb.append(c);
                    }
                }
            }
        }
        sb.append('"');
    }

    private static final class Parser {
        private final String s;
        private int pos;

        Parser(String s) {
            this.s = s;
        }

        boolean hasMore() {
            return pos < s.length();
        }

        void skipWhitespace() {
            while (pos < s.length() && Character.isWhitespace(s.charAt(pos))) {
                pos++;
            }
        }

        Object parseValue() {
            skipWhitespace();
            if (!hasMore()) {
                throw new IllegalArgumentException("JSON 提前结束");
            }
            char c = s.charAt(pos);
            return switch (c) {
                case '{' -> parseObject();
                case '"' -> parseString();
                case 't', 'f' -> parseBoolean();
                case 'n' -> parseNull();
                default -> parseNumber();
            };
        }

        private Object parseObject() {
            pos++; // '{'
            Map<String, Object> map = new LinkedHashMap<>();
            skipWhitespace();
            if (hasMore() && s.charAt(pos) == '}') {
                pos++;
                return map;
            }
            while (true) {
                skipWhitespace();
                String key = parseString();
                skipWhitespace();
                if (!hasMore() || s.charAt(pos) != ':') {
                    throw new IllegalArgumentException("JSON 对象缺少 ':'");
                }
                pos++;
                map.put(key, parseValue());
                skipWhitespace();
                if (!hasMore()) {
                    throw new IllegalArgumentException("JSON 对象未闭合");
                }
                char c = s.charAt(pos);
                if (c == '}') {
                    pos++;
                    return map;
                }
                if (c != ',') {
                    throw new IllegalArgumentException("JSON 对象缺少 ',' 或 '}'");
                }
                pos++;
            }
        }

        private String parseString() {
            if (!hasMore() || s.charAt(pos) != '"') {
                throw new IllegalArgumentException("JSON 字符串缺少 '\"'");
            }
            pos++;
            StringBuilder sb = new StringBuilder();
            while (hasMore()) {
                char c = s.charAt(pos++);
                if (c == '"') {
                    return sb.toString();
                }
                if (c == '\\') {
                    if (!hasMore()) {
                        throw new IllegalArgumentException("JSON 字符串转义不完整");
                    }
                    char esc = s.charAt(pos++);
                    switch (esc) {
                        case '"' -> sb.append('"');
                        case '\\' -> sb.append('\\');
                        case '/' -> sb.append('/');
                        case 'b' -> sb.append('\b');
                        case 'f' -> sb.append('\f');
                        case 'n' -> sb.append('\n');
                        case 'r' -> sb.append('\r');
                        case 't' -> sb.append('\t');
                        case 'u' -> sb.append(parseUnicodeEscape());
                        default -> throw new IllegalArgumentException("非法 JSON 转义: \\" + esc);
                    }
                } else {
                    sb.append(c);
                }
            }
            throw new IllegalArgumentException("JSON 字符串未闭合");
        }

        private char parseUnicodeEscape() {
            if (pos + 4 > s.length()) {
                throw new IllegalArgumentException("非法 \\u 转义");
            }
            String hex = s.substring(pos, pos + 4);
            pos += 4;
            return (char) Integer.parseInt(hex, 16);
        }

        private Object parseBoolean() {
            if (s.startsWith("true", pos)) {
                pos += 4;
                return Boolean.TRUE;
            }
            if (s.startsWith("false", pos)) {
                pos += 5;
                return Boolean.FALSE;
            }
            throw new IllegalArgumentException("非法 JSON 布尔");
        }

        private Object parseNull() {
            if (s.startsWith("null", pos)) {
                pos += 4;
                return null;
            }
            throw new IllegalArgumentException("非法 JSON null");
        }

        private Object parseNumber() {
            int start = pos;
            while (hasMore() && (Character.isDigit(s.charAt(pos)) || "+-.eE".indexOf(s.charAt(pos)) >= 0)) {
                pos++;
            }
            String token = s.substring(start, pos);
            if (token.isEmpty()) {
                throw new IllegalArgumentException("非法 JSON 数字");
            }
            if (token.indexOf('.') >= 0 || token.indexOf('e') >= 0 || token.indexOf('E') >= 0) {
                return Double.parseDouble(token);
            }
            return Long.parseLong(token);
        }
    }
}
