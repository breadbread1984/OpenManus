#!/usr/bin/python3

from absl import flags, app
import gradio as gr

FLAGS = flags.FLAGS

def add_options():
  flags.DEFINE_string('host', default = '0.0.0.0', help = 'service host')
  flags.DEFINE_integer('port', default = 8081, help = 'service port')
  flags.DEFINE_enum('conn_type', default = 'sse', enum_values = {'stdio', 'sse'}, help = 'connection type: stdio or sse')
  flags.DEFINE_string('mcp_host', default = 'http://127.0.0.1:8000/sse', help = 'url to mcp service')

def create_interface():
  # 2) callback functions
  def chatbot_response(user_input, history):
    history.append({'role': 'user', 'content': user_input})
    yield history
    response = "hello the world"
    history.append({'role': 'assistant', 'content': response})
    yield history
  # 3) GUI definition
  with gr.Blocks() as demo:
    with gr.Column():
      with gr.Row(equal_height = True):
        gr.Markdown("# Open Manus")
      with gr.Row(equal_height = True):
        user_input = gr.Textbox(label = "question?", scale = 5)
        submit_btn = gr.Button("submit", scale = 1)
      with gr.Row():
        chatbot = gr.Chatbot(height = 450)
    submit_btn.click(chatbot_response, inputs = [user_input, chatbot], outputs = [chatbot], concurrency_limit = 64)
  return demo

def main(unused_argv):
  demo = create_interface()
  demo.launch(server_name = FLAGS.host, server_port = FLAGS.port)

if __name__ == "__main__":
  add_options()
  app.run(main)
