import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';

const AdminLogin: React.FC = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const navigate = useNavigate();

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const formData = new FormData();
      formData.append('username', username);
      formData.append('password', password);
      
      const response = await axios.post('http://localhost:8000/api/admin/login', formData);
      localStorage.setItem('admin_token', response.data.access_token);
      navigate('/admin/interviews');
    } catch (err) {
      setError('用户名或密码错误');
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
