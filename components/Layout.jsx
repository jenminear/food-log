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
        <NavLink to="/meals/new" className={({isActive}) => 'nav-link' + (isActive ? ' active' : '')}>
          <span className="nav-icon">🍽️</span> Log Meal
        </NavLink>
        <div className="nav-section">Library</div>
        <NavLink to="/recipes"   className={({isActive}) => 'nav-link' + (isActive ? ' active' : '')}>
          <span className="nav-icon">📖</span> Recipes
        </NavLink>
        <NavLink to="/batches"   className={({isActive}) => 'nav-link' + (isActive ? ' active' : '')}>
          <span className="nav-icon">🥘</span> Batches
        </NavLink>
      </nav>
      <main className="main">
        {children}
      </main>
    </div>
  )
}
