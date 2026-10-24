/** 页面启动入口：统一中文组件文案与主题，业务逻辑在App中处理。 */
import React from 'react';
import ReactDOM from 'react-dom/client';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import App from './Workspaces';
import './styles.css';
import './meal.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: '#1677ff', borderRadius: 10, fontSize: 15, fontFamily: 'Inter, "Microsoft YaHei", "PingFang SC", sans-serif', colorText: '#1d2330' } }}>
      <App />
    </ConfigProvider>
  </React.StrictMode>,
);
