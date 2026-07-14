import { Component, type ErrorInfo, type ReactNode } from 'react';

type Props = {
  children: ReactNode;
};

type State = {
  hasError: boolean;
};

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Application render failed', error, info);
  }

  private reload = () => {
    window.location.reload();
  };

  private signOut = () => {
    window.localStorage.removeItem('authToken');
    window.location.assign('/auth');
  };

  render() {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <main className="flex min-h-screen items-center justify-center bg-[#050505] p-6 text-[#F2E8CC]">
        <section className="w-full max-w-md rounded-3xl border border-[#D4AF37]/25 bg-[#0E0E0E] p-8 text-center shadow-2xl">
          <h1 className="text-xl font-bold text-[#D4AF37]">Page failed to load</h1>
          <p className="mt-3 text-sm text-[#CDBB8C]">Try loading the page again. If it still fails, sign in once more.</p>
          <div className="mt-6 flex justify-center gap-3">
            <button type="button" onClick={this.reload} className="rounded-xl bg-[#D4AF37] px-4 py-2 text-sm font-bold text-black">
              Reload
            </button>
            <button type="button" onClick={this.signOut} className="rounded-xl border border-[#D4AF37]/40 px-4 py-2 text-sm font-bold text-[#E8D9AE]">
              Sign in again
            </button>
          </div>
        </section>
      </main>
    );
  }
}
