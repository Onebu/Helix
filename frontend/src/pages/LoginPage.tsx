import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Dna } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { setToken } from '@/lib/auth'
import { getApiBaseUrl } from '@/lib/api-config'

export default function LoginPage() {
  const navigate = useNavigate()
  const [isRegister, setIsRegister] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)

    const endpoint = isRegister ? '/api/auth/register' : '/api/auth/login'
    const body: Record<string, string> = { username, password }
    if (isRegister && email) body.email = email

    try {
      const resp = await fetch(`${getApiBaseUrl()}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })

      if (!resp.ok) {
        const data = await resp.json().catch(() => ({ detail: 'Request failed' }))
        setError(data.detail || `Error ${resp.status}`)
        return
      }

      const data = await resp.json()
      setToken(data.access_token, data.username)
      navigate('/prompts', { replace: true })
    } catch {
      setError('Could not connect to server')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center space-y-2">
          <div className="flex items-center justify-center gap-2">
            <Dna className="h-7 w-7 text-primary" />
            <span className="text-2xl font-bold text-foreground">Helix</span>
          </div>
          <p className="text-sm text-muted-foreground">
            {isRegister ? 'Create your account' : 'Sign in to continue'}
          </p>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <label htmlFor="username" className="text-sm font-medium text-foreground">
                Username
              </label>
              <Input
                id="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="username"
                required
                autoComplete="username"
                autoFocus
              />
            </div>

            {isRegister && (
              <div className="space-y-2">
                <label htmlFor="email" className="text-sm font-medium text-foreground">
                  Email <span className="text-muted-foreground">(optional)</span>
                </label>
                <Input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="email@example.com"
                  autoComplete="email"
                />
              </div>
            )}

            <div className="space-y-2">
              <label htmlFor="password" className="text-sm font-medium text-foreground">
                Password
              </label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="password"
                required
                autoComplete={isRegister ? 'new-password' : 'current-password'}
              />
            </div>

            {error && (
              <p className="text-sm text-destructive">{error}</p>
            )}

            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? 'Loading...' : isRegister ? 'Create Account' : 'Sign In'}
            </Button>

            <p className="text-center text-sm text-muted-foreground">
              {isRegister ? 'Already have an account?' : "Don't have an account?"}{' '}
              <button
                type="button"
                onClick={() => { setIsRegister(!isRegister); setError(null) }}
                className="text-primary hover:underline font-medium"
              >
                {isRegister ? 'Sign in' : 'Register'}
              </button>
            </p>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
