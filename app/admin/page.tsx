import Dashboard from './Dashboard';
export const metadata = {
  title: 'Content dashboard | Elijah Peters',
  robots: {
    index: false,
    follow: false
  },
  alternates: {
    canonical: '/admin'
  }
};
export default function AdminPage() {
  return <Dashboard />;
}
