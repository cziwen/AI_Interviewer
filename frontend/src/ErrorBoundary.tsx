import { Component, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: { componentStack: string }) {
    console.error('App Error:', error, errorInfo);
  }

  render() {
    if (this.state.hasError && this.state.error) {
      return (
        <div style={{
          padding: '40px',
          maxWidth: '600px',
          margin: '50px auto',
          fontFamily: 'sans-serif',
          backgroundColor: 'var(--surface)',
          border: '1px solid var(--error)',
          borderRadius: '8px',
          color: 'var(--text)'
        }}>
          <h2 style={{ color: 'var(--error)' }}>页面加载出错</h2>
          <pre style={{ overflow: 'auto', fontSize: '12px', backgroundColor: 'var(--bg)', padding: '10px', borderRadius: '4px', border: '1px solid var(--border)', color: 'var(--text)' }}>
            {this.state.error.toString()}
          </pre>
          <button
            onClick={() => window.location.reload()}
            style={{ marginTop: '20px', padding: '10px 20px', cursor: 'pointer', backgroundColor: 'var(--primary)', color: 'white', border: 'none', borderRadius: '4px' }}
          >
            刷新页面
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
