package com.msz.acc.infrastructure.tx;

import com.msz.acc.repository.RequestSqlSessionHolder;
import org.apache.ibatis.session.SqlSession;

import java.lang.reflect.InvocationHandler;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;

/**
 * Mapper 事务感知代理工厂（design D3/D7）：{@link java.lang.reflect.Proxy} 让 6 个 Mapper Bean 保持
 * 「单例 + 接口类型」的既有注入形态（20+ 处构造注入点与全部测试无需改动），但不再返回某个固定会话上的
 * Mapper 实例——每次方法调用都向 {@link RequestSqlSessionHolder} 索取**当前请求会话**上的真实 Mapper 并转发。
 *
 * <p>语义要点：</p>
 * <ul>
 *   <li><b>事务感知</b>：请求内所有 Mapper 调用落在同一会话/连接上，随请求边界统一提交或回滚（D8 隐式 REQUIRED）；</li>
 *   <li><b>无请求上下文降级</b>：非 Web 调用路径退化为「单次自动提交会话 + 调用后关闭」（D7）；</li>
 *   <li><b>异常透明</b>：{@link InvocationTargetException} 解包后原样抛出，类型与消息均不被包装改变；</li>
 *   <li><b>Object 方法本地处理</b>：{@code toString/hashCode/equals} 不触会话——日志、容器与 Mockito 等
 *       对单例 Bean 的调用不得因此占用数据库连接。</li>
 * </ul>
 */
public final class TransactionalMapperProxy {

    private final RequestSqlSessionHolder holder;

    public TransactionalMapperProxy(RequestSqlSessionHolder holder) {
        this.holder = holder;
    }

    /** 为 Mapper 接口创建事务感知代理（返回类型与接口一致，可直接注入 Flow/Controller）。 */
    @SuppressWarnings("unchecked")
    public <T> T create(Class<T> mapperType) {
        if (mapperType == null || !mapperType.isInterface()) {
            throw new IllegalArgumentException("Mapper 代理仅支持接口类型: " + mapperType);
        }
        return (T) Proxy.newProxyInstance(mapperType.getClassLoader(), new Class<?>[]{mapperType},
                new MapperHandler(mapperType));
    }

    /** 调用处理器：按「当前请求会话 → 无上下文降级」两条路径转发。 */
    private final class MapperHandler implements InvocationHandler {

        private final Class<?> mapperType;

        MapperHandler(Class<?> mapperType) {
            this.mapperType = mapperType;
        }

        @Override
        public Object invoke(Object proxy, Method method, Object[] args) throws Throwable {
            if (method.getDeclaringClass() == Object.class) {
                return invokeObjectMethod(proxy, method, args);
            }
            if (holder.isRequestActive()) {
                return invokeOn(holder.currentSession(), method, args);
            }
            return holder.executeStandalone(session -> invokeOn(session, method, args));
        }

        /** 在给定会话的真实 Mapper 上执行调用，解包反射异常以保持原始类型与消息。 */
        private Object invokeOn(SqlSession session, Method method, Object[] args) throws Throwable {
            Object target = session.getMapper(mapperType);
            try {
                return method.invoke(target, args);
            } catch (InvocationTargetException e) {
                throw e.getTargetException();
            }
        }

        /** Object 方法不触会话：避免日志/容器调用意外占用数据库连接。 */
        private Object invokeObjectMethod(Object proxy, Method method, Object[] args) {
            return switch (method.getName()) {
                case "toString" -> "TransactionalMapperProxy(" + mapperType.getName() + ")";
                case "hashCode" -> System.identityHashCode(proxy);
                case "equals" -> proxy == args[0];
                default -> throw new IllegalStateException("不支持的 Object 方法: " + method.getName());
            };
        }
    }
}
