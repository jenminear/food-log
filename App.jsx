import { Routes, Route } from 'react-router-dom'
import { Layout } from './components/Layout'
import Today        from './pages/Today'
import Reports      from './pages/Reports'
import Recipes      from './pages/Recipes'
import RecipeDetail from './pages/RecipeDetail'
import Batches      from './pages/Batches'
import LogMeal      from './pages/Meals'

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/"               element={<Today />} />
        <Route path="/reports"        element={<Reports />} />
        <Route path="/recipes"        element={<Recipes />} />
        <Route path="/recipes/:id"    element={<RecipeDetail />} />
        <Route path="/batches"        element={<Batches />} />
        <Route path="/batches/:id"    element={<Batches />} />
        <Route path="/meals/new"      element={<LogMeal />} />
      </Routes>
    </Layout>
  )
}
