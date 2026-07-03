import { render, screen } from '@testing-library/react'
import { BandDisplay } from '../components/BandDisplay'

describe('BandDisplay', () => {
  it('renders unknown band in grey', () => {
    render(<BandDisplay band="unknown" confidence={0} />)
    const badge = screen.getByTestId('band-badge')
    expect(badge).toHaveClass('band-unknown')
    expect(badge).toHaveTextContent('Unknown')
  })

  it('renders child band in red', () => {
    render(<BandDisplay band="child" confidence={0.8} />)
    const badge = screen.getByTestId('band-badge')
    expect(badge).toHaveClass('band-child')
    expect(badge).toHaveTextContent('Child')
  })

  it('shows confidence percentage', () => {
    render(<BandDisplay band="adult" confidence={0.72} />)
    expect(screen.getByText('Confidence: 72%')).toBeInTheDocument()
  })

  it('renders teen band', () => {
    render(<BandDisplay band="teen" confidence={0.5} />)
    expect(screen.getByTestId('band-badge')).toHaveClass('band-teen')
  })
})
