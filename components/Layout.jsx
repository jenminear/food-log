import { NavLink } from 'react-router-dom'

export function Layout({ children }) {
  return (
    <div className="shell">
      <nav className="nav">
        <div className="nav-logo">Food Log</div>
        <div className="nav-section">Daily</div>
        <NavLink to="/"          className={({isActive}) => 'nav-link' + (isActive ? ' active' : '')}>
          <span className="nav-icon">📊</span> Today
        </NavLink>
        <NavLink to="/reports"   className={({isActive}) => 'nav-link' + (isActive ? ' active' : '')}>
          <span className="nav-icon">📈</span> Reports
        </NavLink>
        <div className="nav-section">Library</div>
        <NavLink to="/recipes"   className={({isActive}) => 'nav-link' + (isActive ? ' active' : '')}>
          <span className="nav-icon">📖</span> Recipes
        </NavLink>
        <NavLink to="/ingredients" className={({isActive}) => 'nav-link' + (isActive ? ' active' : '')}>
          <span className="nav-icon">🥕</span> Ingredients
        </NavLink>
        <div className="nav-section">Account</div>
        <NavLink to="/settings" className={({isActive}) => 'nav-link' + (isActive ? ' active' : '')}>
          <span className="nav-icon">⚙️</span> Settings
        </NavLink>
      </nav>
      <main className="main">
        {children}
      </main>
    </div>
  )
}
