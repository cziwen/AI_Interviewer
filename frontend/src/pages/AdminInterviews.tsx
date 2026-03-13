import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { Link } from 'react-router-dom';
import { createInterview, getJobProfiles, uploadJobProfile } from '../api';

interface InterviewSummary {
  id: number;
  name: string;
  position: string;
  status: string;
  created_at: string;
  total_score: number | null;
}

interface JobProfileSummary {
  position_key: string;
  position_name: string;
}

const AdminInterviews: React.FC = () => {
  const [interviews, setInterviews] = useState<InterviewSummary[]>([]);
  const [jobProfiles, setJobProfiles] = useState<JobProfileSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<{ code: number; message: string } | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [showJobModal, setShowJobModal] = useState(false);
  const [newInterview, setNewInterview] = useState({ name: '', position_key: '', resume_brief: '' });
  const [newJob, setNewJob] = useState<{
    position_key: string;
    position_name: string;
    jd_file: File | null;
    question_csv: File | null;
  }>({
    position_key: '',
    position_name: '',
    jd_file: null,
    question_csv: null,
  });
  const [createdLink, setCreatedLink] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [jobSubmitting, setJobSubmitting] = useState(false);

  const fetchInterviews = () => {
    const token = localStorage.getItem('admin_token');
    axios.get('http://localhost:8000/api/admin/interviews', {
      headers: { Authorization: `Bearer ${token}` }
    })
    .then(res => setInterviews(res.data))
    .catch(err => {
      setError({
        code: err.response?.status || 500,
        message: err.response?.data?.detail || err.message
      });
    })
    .finally(() => setLoading(false));
  };

  const fetchJobProfiles = async () => {
    try {
      const data = await getJobProfiles();
      setJobProfiles(data);
    } catch (err: any) {
      console.error('Failed to fetch job profiles:', err);
      setError({
        code: err.response?.status || 500,
        message: err.response?.data?.detail || err.message
      });
    }
  };

  useEffect(() => {
    fetchInterviews();
    fetchJobProfiles();
  }, []);

  const handleCreate = async () => {
    if (!newInterview.position_key) {
      alert('请选择岗位');
      return;
    }
    setSubmitting(true);
    try {
      const res = await createInterview(newInterview);
      const link = `${window.location.origin}/interview/${res.link_token}`;
      setCreatedLink(link);
      fetchInterviews();
    } catch (err: any) {
      setError({
        code: err.response?.status || 500,
        message: err.response?.data?.detail || err.message
      });
    } finally {
      setSubmitting(false);
    }
  };

  const handleJobUpload = async () => {
    if (!newJob.position_key || !newJob.jd_file || !newJob.question_csv) {
      alert('请填写岗位 Key 并上传 JD JSON 和 题库 CSV');
      return;
    }
    setJobSubmitting(true);
    try {
      await uploadJobProfile({
        position_key: newJob.position_key,
        position_name: newJob.position_name,
        jd_file: newJob.jd_file,
        question_csv: newJob.question_csv,
      });
      alert('岗位创建成功');
      setShowJobModal(false);
      setNewJob({ position_key: '', position_name: '', jd_file: null, question_csv: null });
      fetchJobProfiles();
    } catch (err: any) {
      setError({
        code: err.response?.status || 500,
        message: err.response?.data?.detail || err.message
      });
    } finally {
      setJobSubmitting(false);
    }
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm('确定要删除这场面试吗？此操作不可撤销。')) return;
    
    const token = localStorage.getItem('admin_token');
    try {
      await axios.delete(`http://localhost:8000/api/admin/interviews/${id}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setInterviews(interviews.filter(i => i.id !== id));
    } catch (err: any) {
      setError({
        code: err.response?.status || 500,
        message: err.response?.data?.detail || err.message
      });
    }
  };

  const copyToClipboard = () => {
    navigator.clipboard.writeText(createdLink);
    alert('链接已复制到剪贴板');
  };

  const closeModal = () => {
    setShowModal(false);
    setCreatedLink('');
    setNewInterview({ name: '', position: '', resume_brief: '' });
  };

  if (loading) return <div style={{ padding: '20px', color: 'var(--text)' }}>加载中...</div>;

  return (
    <div style={{ padding: '20px', color: 'var(--text)' }}>
      {error && (
        <div style={{
          padding: '10px 20px',
          backgroundColor: 'rgba(255, 77, 79, 0.1)',
          border: '1px solid #ff4d4f',
          borderRadius: '4px',
          color: '#ff4d4f',
          marginBottom: '20px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}>
          <span>
            <strong>Error {error.code}:</strong> {error.message}
          </span>
          <button onClick={() => setError(null)} style={{ background: 'none', border: 'none', color: '#ff4d4f', cursor: 'pointer', fontSize: '18px' }}>✕</button>
        </div>
      )}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <h2 style={{ color: 'var(--text)', margin: 0 }}>面试列表</h2>
        <div style={{ display: 'flex', gap: '10px' }}>
          <button 
            onClick={() => setShowJobModal(true)}
            style={{
              padding: '10px 20px',
              backgroundColor: '#52c41a',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer'
            }}
          >
            岗位管理
          </button>
          <button 
            onClick={() => setShowModal(true)}
            style={{
              padding: '10px 20px',
              backgroundColor: '#1890ff',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer'
            }}
          >
            创建面试
          </button>
        </div>
      </div>

      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ borderBottom: '2px solid var(--border)' }}>
            <th style={{ textAlign: 'left', padding: '10px' }}>候选人</th>
            <th style={{ textAlign: 'left', padding: '10px' }}>岗位</th>
            <th style={{ textAlign: 'left', padding: '10px' }}>状态</th>
            <th style={{ textAlign: 'left', padding: '10px' }}>总分</th>
            <th style={{ textAlign: 'left', padding: '10px' }}>时间</th>
            <th style={{ textAlign: 'left', padding: '10px' }}>操作</th>
          </tr>
        </thead>
        <tbody>
          {interviews.map(i => (
            <tr key={i.id} style={{ borderBottom: '1px solid var(--border)' }}>
              <td style={{ padding: '10px' }}>{i.name || '未填写'}</td>
              <td style={{ padding: '10px' }}>{i.position || '未填写'}</td>
              <td style={{ padding: '10px' }}>{i.status}</td>
              <td style={{ padding: '10px' }}>{i.total_score ?? '-'}</td>
              <td style={{ padding: '10px' }}>{new Date(i.created_at).toLocaleString()}</td>
              <td style={{ padding: '10px' }}>
                <Link to={`/admin/interviews/${i.id}`} style={{ color: 'var(--link)', marginRight: '15px' }}>查看详情</Link>
                <button 
                  onClick={() => handleDelete(i.id)}
                  style={{ 
                    color: 'var(--error)', 
                    background: 'none', 
                    border: 'none', 
                    padding: 0, 
                    cursor: 'pointer',
                    textDecoration: 'underline',
                    fontSize: 'inherit',
                    fontFamily: 'inherit'
                  }}
                >
                  删除
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {showModal && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0,0,0,0.5)',
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          zIndex: 1000
        }}>
          <div style={{
            backgroundColor: '#fff',
            padding: '30px',
            borderRadius: '8px',
            width: '400px',
            boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
            color: '#333'
          }}>
            {!createdLink ? (
              <>
                <h3 style={{ marginTop: 0 }}>创建新面试</h3>
                <div style={{ marginBottom: '15px' }}>
                  <label style={{ display: 'block', marginBottom: '5px' }}>候选人姓名</label>
                  <input 
                    type="text" 
                    value={newInterview.name}
                    onChange={e => setNewInterview({...newInterview, name: e.target.value})}
                    style={{ width: '100%', padding: '8px', boxSizing: 'border-box' }}
                    placeholder="可选"
                  />
                </div>
                <div style={{ marginBottom: '15px' }}>
                  <label style={{ display: 'block', marginBottom: '5px' }}>申请岗位</label>
                  <select 
                    value={newInterview.position_key}
                    onChange={e => setNewInterview({...newInterview, position_key: e.target.value})}
                    style={{ width: '100%', padding: '8px', boxSizing: 'border-box' }}
                  >
                    <option value="">请选择岗位</option>
                    {jobProfiles.map(jp => (
                      <option key={jp.position_key} value={jp.position_key}>
                        {jp.position_name || jp.position_key}
                      </option>
                    ))}
                  </select>
                </div>
                <div style={{ marginBottom: '20px' }}>
                  <label style={{ display: 'block', marginBottom: '5px' }}>简历摘要/背景</label>
                  <textarea 
                    value={newInterview.resume_brief}
                    onChange={e => setNewInterview({...newInterview, resume_brief: e.target.value})}
                    style={{ width: '100%', padding: '8px', height: '80px', boxSizing: 'border-box' }}
                    placeholder="可选，用于生成针对性问题"
                  />
                </div>
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
                  <button onClick={closeModal} style={{ padding: '8px 16px', cursor: 'pointer' }}>取消</button>
                  <button 
                    onClick={handleCreate} 
                    disabled={submitting}
                    style={{ 
                      padding: '8px 16px', 
                      backgroundColor: '#1890ff', 
                      color: 'white', 
                      border: 'none', 
                      borderRadius: '4px',
                      cursor: submitting ? 'not-allowed' : 'pointer',
                      opacity: submitting ? 0.7 : 1
                    }}
                  >
                    {submitting ? '创建中...' : '立即创建'}
                  </button>
                </div>
              </>
            ) : (
              <>
                <h3 style={{ marginTop: 0, color: '#52c41a' }}>创建成功！</h3>
                <p style={{ marginBottom: '10px' }}>面试链接已生成：</p>
                <div style={{ 
                  padding: '10px', 
                  backgroundColor: '#f5f5f5', 
                  borderRadius: '4px', 
                  wordBreak: 'break-all',
                  fontSize: '14px',
                  marginBottom: '20px',
                  border: '1px solid #ddd'
                }}>
                  {createdLink}
                </div>
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
                  <button onClick={copyToClipboard} style={{ padding: '8px 16px', backgroundColor: '#52c41a', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer' }}>复制链接</button>
                  <button onClick={closeModal} style={{ padding: '8px 16px', cursor: 'pointer' }}>关闭</button>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {showJobModal && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0,0,0,0.5)',
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          zIndex: 1000
        }}>
          <div style={{
            backgroundColor: '#fff',
            padding: '30px',
            borderRadius: '8px',
            width: '450px',
            boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
            color: '#333'
          }}>
            <h3 style={{ marginTop: 0 }}>岗位管理 - 创建新岗位</h3>
            <div style={{ marginBottom: '15px' }}>
              <label style={{ display: 'block', marginBottom: '5px' }}>岗位 Key (唯一标识)</label>
              <input 
                type="text" 
                value={newJob.position_key}
                onChange={e => setNewJob({...newJob, position_key: e.target.value})}
                style={{ width: '100%', padding: '8px', boxSizing: 'border-box' }}
                placeholder="如: backend_engineer"
              />
            </div>
            <div style={{ marginBottom: '15px' }}>
              <label style={{ display: 'block', marginBottom: '5px' }}>岗位名称 (展示用)</label>
              <input 
                type="text" 
                value={newJob.position_name}
                onChange={e => setNewJob({...newJob, position_name: e.target.value})}
                style={{ width: '100%', padding: '8px', boxSizing: 'border-box' }}
                placeholder="如: 高级后端工程师"
              />
            </div>
            <div style={{ marginBottom: '15px' }}>
              <label style={{ display: 'block', marginBottom: '5px' }}>JD JSON 文件</label>
              <input 
                type="file" 
                accept=".json"
                onChange={e => setNewJob({...newJob, jd_file: e.target.files?.[0] || null})}
                style={{ width: '100%', padding: '8px', boxSizing: 'border-box' }}
              />
              <small style={{ color: '#666' }}>包含 main_question_count, expected_duration_minutes 等</small>
            </div>
            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', marginBottom: '5px' }}>题库 CSV 文件</label>
              <input 
                type="file" 
                accept=".csv"
                onChange={e => setNewJob({...newJob, question_csv: e.target.files?.[0] || null})}
                style={{ width: '100%', padding: '8px', boxSizing: 'border-box' }}
              />
              <small style={{ color: '#666' }}>包含 question, reference 两列</small>
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
              <button onClick={() => setShowJobModal(false)} style={{ padding: '8px 16px', cursor: 'pointer' }}>取消</button>
              <button 
                onClick={handleJobUpload} 
                disabled={jobSubmitting}
                style={{ 
                  padding: '8px 16px', 
                  backgroundColor: '#52c41a', 
                  color: 'white', 
                  border: 'none', 
                  borderRadius: '4px',
                  cursor: jobSubmitting ? 'not-allowed' : 'pointer',
                  opacity: jobSubmitting ? 0.7 : 1
                }}
              >
                {jobSubmitting ? '上传中...' : '上传并创建'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AdminInterviews;
