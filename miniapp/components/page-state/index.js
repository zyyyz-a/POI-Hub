Component({
  properties: {
    state: { type: String, value: 'content' },
    message: { type: String, value: '' },
    actionText: { type: String, value: '' }
  },
  methods: {
    onAction() {
      this.triggerEvent('action')
    }
  }
})
