/** HTTP 客户端封装 */
import axios from 'axios'

const client = axios.create({
  baseURL: 'http://localhost:8000',
  timeout: 10000,
})

client.interceptors.response.use(
  (response) => response,
  (error) => {
    const msg = error.response?.data?.error?.message || '网络错误'
    console.error(`[API] ${error.config?.url}: ${msg}`)
    return Promise.reject(error)
  },
)

export default client
