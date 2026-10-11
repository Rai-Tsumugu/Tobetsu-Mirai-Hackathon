import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';

const root = document.getElementById('root');
if (!root) throw new Error('アプリ表示領域が見つかりません');

createRoot(root).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
