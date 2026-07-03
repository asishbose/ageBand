import { render, screen } from '@testing-library/react'
import { PostureDisplay } from '../components/PostureDisplay'

describe('PostureDisplay', () => {
  it('standard posture has green colour class', () => {
    render(<PostureDisplay posture={{ level: 'standard', flags: {} }} />)
    expect(screen.getByTestId('posture-badge')).toHaveClass('posture-standard')
  })

  it('blocked posture has red colour class', () => {
    render(<PostureDisplay posture={{ level: 'blocked', flags: {} }} />)
    expect(screen.getByTestId('posture-badge')).toHaveClass('posture-blocked')
  })

  it('caution posture has caution class', () => {
    render(<PostureDisplay posture={{ level: 'caution', flags: {} }} />)
    expect(screen.getByTestId('posture-badge')).toHaveClass('posture-caution')
  })

  it('renders active flags as chips', () => {
    render(<PostureDisplay posture={{ level: 'restricted', flags: { minor_likely: true, explicit_blocked: false } }} />)
    expect(screen.getByText('minor_likely')).toBeInTheDocument()
    expect(screen.queryByText('explicit_blocked')).not.toBeInTheDocument()
  })
})
