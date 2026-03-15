import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API_BASE_URL } from '../api';

const AdminLogin: React.FC = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const navigate = useNavigate();

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const formData = new URLSearchParams({
        username,
        password,
      });

      const response = await axios.post(`${API_BASE_URL}/admin/login`, formData, {
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
        },
      });
      localStorage.setItem('admin_token', response.data.access_token);
      navigate('/admin/interviews');
    } catch (err) {
      if (!axios.isAxiosError(err)) {
        setError('登录失败，请稍后重试');
        return;
      }

      if (!err.response) {
        setError('网络错误，请检查连接');
        return;
      }

      const detail = err.response.data?.detail;
      if (err.response.status === 401) {
        setError('用户名或密码错误');
      } else if (err.response.status >= 500) {
        setError('服务器错误，请稍后重试');
      } else if (typeof detail === 'string' && detail.trim()) {
        setError(detail);
      } else if (Array.isArray(detail) && detail.length > 0) {
        const firstDetail = detail[0];
        const detailMessage = typeof firstDetail?.msg === 'string' ? firstDetail.msg : '';
        setError(detailMessage || '请求参数错误，请检查输入');
      } else {
        setError('登录失败，请检查输入后重试');
      }
    }
  };

  return (
    <div style={{
      maxWidth: '400px',
      margin: '100px auto',
      padding: '20px',
      border: '1px solid var(--border)',
      borderRadius: '8px',
      backgroundColor: 'var(--surface)',
      color: 'var(--text)',
      boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
    }}>
      <h2 style={{ color: 'var(--text)', marginTop: 0 }}>管理员登录</h2>
      <form onSubmit={handleLogin}>
        <div style={{ marginBottom: '10px' }}>
          <label>用户名: </label>
          <input type="text" value={username} onChange={(e) => setUsername(e.target.value)} style={{ width: '100%', padding: '8px', boxSizing: 'border-box', border: '1px solid var(--border)', borderRadius: '4px', backgroundColor: 'var(--bg)', color: 'var(--text)' }} />
        </div>
        <div style={{ marginBottom: '10px' }}>
          <label>密码: </label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} style={{ width: '100%', padding: '8px', boxSizing: 'border-box', border: '1px solid var(--border)', borderRadius: '4px', backgroundColor: 'var(--bg)', color: 'var(--text)' }} />
        </div>
        {error && <p style={{ color: 'var(--error)' }}>{error}</p>}
        <button type="submit" style={{ width: '100%', padding: '10px' }}>登录</button>
      </form>
    </div>
  );
};

export default AdminLogin;
