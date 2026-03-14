import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { API_BASE_URL } from '../api';

const AdminInterviewDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<{ code: number; message: string } | null>(null);

  useEffect(() => {
    const token = localStorage.getItem('admin_token');
    axios.get(`${API_BASE_URL}/admin/interviews/${id}`, {
      headers: { Authorization: `Bearer ${token}` }
    })
    .then(res => setData(res.data))
    .catch(err => {
      setError({
        code: err.response?.status || 500,
        message: err.response?.data?.detail || err.message
      });
    })
    .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <div style={{ padding: '20px', color: 'var(--text)' }}>加载中...</div>;
  if (!data) return <div style={{ padding: '20px', color: 'var(--text)' }}>未找到面试详情</div>;

  const { interview, answers } = data;
  const sortedAnswers = [...(answers || [])].sort((a: any, b: any) => {
    const aKey = a.created_at || a.id || 0;
    const bKey = b.created_at || b.id || 0;
    if (aKey === bKey) return 0;
    return aKey > bKey ? 1 : -1;
  });
  const introAnswers = sortedAnswers.filter((a: any) => a.question_index === 0);

  return (
    <div style={{ padding: '20px', maxWidth: '800px', margin: '0 auto', color: 'var(--text)' }}>
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
      <button 
        onClick={() => navigate('/admin/interviews')}
        style={{ 
          marginBottom: '20px', 
          padding: '8px 16px', 
          cursor: 'pointer',
          backgroundColor: 'var(--surface)',
          color: 'var(--text)',
          border: '1px solid var(--border)',
          borderRadius: '4px'
        }}
      >
        ← 返回列表
      </button>
      <h2 style={{ color: 'var(--text)' }}>面试详情: {interview.name} - {interview.position}</h2>
      
      <div style={{ marginBottom: '30px', padding: '20px', backgroundColor: 'var(--surface)', borderRadius: '8px', border: '1px solid var(--border)' }}>
        <h3 style={{ color: 'var(--text)', marginTop: 0 }}>AI 评分结果</h3>
        {interview.evaluation_result ? (
          <div>
            <p><strong>总分:</strong> {interview.evaluation_result.total_score}</p>
            <p><strong>评语:</strong> {interview.evaluation_result.comment}</p>
            <h4 style={{ color: 'var(--text)' }}>维度分:</h4>
            <ul>
              {Object.entries(interview.evaluation_result.dimension_scores).map(([k, v]: any) => (
                <li key={k}>{k}: {v}</li>
              ))}
            </ul>
          </div>
        ) : (
          <p style={{ color: 'var(--text-muted)' }}>暂无评分（面试可能尚未完成或正在评估中）</p>
        )}
      </div>

      <h3 style={{ color: 'var(--text)' }}>问答记录</h3>
      {introAnswers.length > 0 && (
        <div style={{ marginBottom: '20px', borderLeft: '4px solid #6c757d', paddingLeft: '15px' }}>
          <p><strong>自我介绍</strong></p>
          <p>
            <strong>回答:</strong>{" "}
            {introAnswers
              .map((a: any) => a.transcript)
              .filter((t: string) => Boolean(t))
              .join(' ')
              || '未回答'}
          </p>
          {introAnswers
            .filter((a: any) => a.audio_url)
            .map((a: any, idx: number) => (
              <p key={`intro-audio-${idx}`}>
                <small style={{ color: 'var(--text-muted)' }}>音频文件: {a.audio_url}</small>
              </p>
            ))}
        </div>
      )}
      {interview.question_set.map((q: any, idx: number) => {
        const orderIndex = q.order_index ?? (idx + 1);
        const matchedAnswers = sortedAnswers.filter((a: any) => a.question_index === orderIndex);
        const mergedTranscript = matchedAnswers
          .map((a: any) => a.transcript)
          .filter((t: string) => Boolean(t))
          .join(' ');
        return (
          <div key={idx} style={{ marginBottom: '20px', borderLeft: '4px solid var(--primary)', paddingLeft: '15px' }}>
            <p><strong>Q{orderIndex}: {q.question_text}</strong></p>
            <p><strong>回答:</strong> {mergedTranscript || '未回答'}</p>
            {matchedAnswers
              .filter((a: any) => a.audio_url)
              .map((a: any, audioIdx: number) => (
                <p key={`q-${orderIndex}-audio-${audioIdx}`}>
                  <small style={{ color: 'var(--text-muted)' }}>音频文件: {a.audio_url}</small>
                </p>
              ))}
          </div>
        );
      })}
    </div>
  );
};

export default AdminInterviewDetail;
