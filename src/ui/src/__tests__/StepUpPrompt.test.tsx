import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { StepUpPrompt } from '../components/StepUpPrompt'

describe('StepUpPrompt', () => {
  it('renders nothing when step_up is null', () => {
    const { container } = render(<StepUpPrompt stepUp={null} onAction={() => undefined} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows Confirm Age button when action is confirm', () => {
    render(
      <StepUpPrompt
        stepUp={{ message_text: 'Please confirm age.', action: 'confirm' }}
        onAction={() => undefined}
      />
    )
    expect(screen.getByRole('button', { name: 'Confirm Age' })).toBeInTheDocument()
  })

  it('clicking Confirm Age calls onAction("confirm")', async () => {
    const user = userEvent.setup()
    const handler = vi.fn()
    render(
      <StepUpPrompt
        stepUp={{ message_text: 'Please confirm age.', action: 'confirm' }}
        onAction={handler}
      />
    )
    await user.click(screen.getByRole('button', { name: 'Confirm Age' }))
    expect(handler).toHaveBeenCalledWith('confirm')
  })

  it('shows message text', () => {
    render(
      <StepUpPrompt
        stepUp={{ message_text: 'Identity check required.', action: 'restrict' }}
        onAction={() => undefined}
      />
    )
    expect(screen.getByText('Identity check required.')).toBeInTheDocument()
  })
})
