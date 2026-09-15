-- 网关级限流固定窗口计数(F3,Redis+Lua 原子):
-- KEYS[1]=桶 key;ARGV[1]=窗口毫秒;ARGV[2]=容量。
-- 返回 1 = 放行,0 = 超限拒绝。
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[1]))
end
if current > tonumber(ARGV[2]) then
  return 0
end
return 1
