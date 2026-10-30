/**
 * 前端轻量日志工具。
 *
 * 规则：
 * - error / warn：始终输出到浏览器控制台
 * - info / debug：仅在开发模式（import.meta.env.DEV）或
 *   localStorage.TDASHBOARD_DEBUG === '1' 时输出
 *
 * 用法：const log = createLogger('api'); log.info('...')
 */

type Level = 'debug' | 'info' | 'warn' | 'error'

const PREFIX = '[T-Dashboard]'

/** 判断当前级别是否应该打印。 */
function enabled(level: Level): boolean {
  // 错误与警告永远可见，便于线上排查
  if (level === 'error' || level === 'warn') return true
  try {
    // 用户可在控制台手动打开详细日志
    if (typeof localStorage !== 'undefined' && localStorage.getItem('TDASHBOARD_DEBUG') === '1') {
      return true
    }
  } catch {
    /* 隐私模式等可能导致 localStorage 不可用，忽略 */
  }
  // Vite 开发服务器下默认打开 info/debug
  return Boolean(import.meta.env.DEV)
}

/** 按级别选择 console 方法并打印「前缀 + 作用域 + 消息」。 */
function write(level: Level, scope: string, message: string, extra?: unknown) {
  if (!enabled(level)) return
  const line = `${PREFIX} ${scope} ${message}`
  const fn =
    level === 'error'
      ? console.error
      : level === 'warn'
        ? console.warn
        : level === 'debug'
          ? console.debug
          : console.info
  // 有附加对象时作为第二参数，方便展开查看
  if (extra !== undefined) fn(line, extra)
  else fn(line)
}

/** 创建带作用域名的 logger，便于过滤控制台输出。 */
export function createLogger(scope: string) {
  return {
    debug: (message: string, extra?: unknown) => write('debug', scope, message, extra),
    info: (message: string, extra?: unknown) => write('info', scope, message, extra),
    warn: (message: string, extra?: unknown) => write('warn', scope, message, extra),
    error: (message: string, extra?: unknown) => write('error', scope, message, extra),
  }
}
