import sys
import numpy as np
from transformers import AutoTokenizer
from openvino.runtime import Core, Tensor
from pathlib import Path

utils_file_path = Path('.')
sys.path.append(str(utils_file_path))
from utils import process_response, sample_next_token


class ChatGLMModel():

    def __init__(self,
                 model_path='./chatglm2/ir_model',
                 device='CPU') -> None:
        
        ir_model_path = Path(model_path)
        ir_model = ir_model_path / "chatglm2.xml"
        
        print(" --- loading tokenizer --- ")
        self.tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
        core = Core()

        print(" --- reading model --- ")
        # read the model and corresponding weights from file
        self.model = core.read_model(ir_model)
        # input & output names
        input_names = {
            key.get_any_name(): idx
            for idx, key in enumerate(self.model.inputs)
        }
        output_names = {
            key.get_any_name(): idx
            for idx, key in enumerate(self.model.outputs)
        }
        self.key_value_input_names = [
            key for key in input_names if "key_values" in key
        ]
        self.key_value_output_names = [
            key for key in output_names if "present" in key
        ]

        print(" --- model compiling --- ")
        # compile the model for CPU devices
        self.request = core.compile_model(
            model=self.model, device_name=device).create_infer_request()
        self.eos_token_id = self.tokenizer.eos_token_id

    def build_inputs(self,
                     history: list[tuple[str, str]],
                     query: str,
                     system: str = "",
                     max_input_tokens: int = 2048):
        prompt = "{}\n\n".format(system)
        for i, (old_query, response) in enumerate(history):
            prompt += "[Round {}]\n\n问：{}\n\n答：{}\n\n".format(
                i + 1, old_query, response)
        prompt += "[Round {}]\n\n问：{}\n\n答：".format(len(history) + 1, query)
        tokens = self.tokenizer([prompt], return_tensors="np")
        input_tokens = tokens['input_ids'][:][-max_input_tokens:]
        return input_tokens

    def generate_sequence(self,
                          input_ids,
                          max_generated_tokens=100,
                          top_k=20,
                          top_p=0.7,
                          temperature=1):
        position_ids = np.arange(0, input_ids.shape[1], dtype=np.int64)
        position_ids = np.expand_dims(position_ids,axis=0)
        past_key_values = None
        num_iteration = 0
        output_tokens = []
        new_position_id = np.copy(position_ids[..., -1:])
        while True:
            inputs = {"input_ids": input_ids}
            if past_key_values is not None:
                new_position_id += 1
                inputs["position_ids"] = new_position_id
                inputs.update(past_key_values)
            else:
                inputs["position_ids"] = position_ids
                shape_input_ids = input_ids.shape
                for input_name in self.key_value_input_names:
                    model_inputs = self.model.input(input_name)
                    shape = model_inputs.get_partial_shape()
                    if shape[0].is_dynamic:
                        shape[0] = 0
                    if shape[1].is_dynamic:
                        shape[1] = shape_input_ids[0]
                    inputs[input_name] = Tensor(
                        model_inputs.get_element_type(), shape.get_shape())
            self.request.start_async(inputs, share_inputs=True)
            self.request.wait()
            num_iteration += 1
            logits = self.request.get_tensor("logits").data
            past_key_values = tuple(
                self.request.get_tensor(key).data
                for key in self.key_value_output_names)
            past_key_values = {
                k: v
                for k, v in zip(self.key_value_input_names, past_key_values)
            }

            next_token = sample_next_token(logits[0, -1],
                                           top_k=top_k,
                                           top_p=top_p,
                                           temperature=temperature)
            output_tokens += [next_token]
            if next_token == self.eos_token_id or len(
                    output_tokens) > max_generated_tokens:
                break

            input_ids = np.array([[next_token]], dtype=np.longlong)
        return output_tokens, num_iteration

    def generate_iterate(self,
                         input_ids,
                         max_generated_tokens,
                         top_k=20,
                         top_p=0.7,
                         temperature=1):
        position_ids = np.arange(0, input_ids.shape[1], dtype=np.int64)
        position_ids = np.expand_dims(position_ids,axis=0)
        past_key_values = None
        output_tokens = []
        new_position_id = np.copy(position_ids[..., -1:])
        while True:
            inputs = {"input_ids": input_ids}
            if past_key_values is not None:
                new_position_id += 1
                inputs["position_ids"] = new_position_id
                inputs.update(past_key_values)
            else:
                inputs["position_ids"] = position_ids
                shape_input_ids = input_ids.shape
                for input_name in self.key_value_input_names:
                    model_inputs = self.model.input(input_name)
                    shape = model_inputs.get_partial_shape()
                    if shape[0].is_dynamic:
                        shape[0] = 0
                    if shape[1].is_dynamic:
                        shape[1] = shape_input_ids[0]
                    inputs[input_name] = Tensor(
                        model_inputs.get_element_type(), shape.get_shape())

            self.request.start_async(inputs, share_inputs=True)
            self.request.wait()
            logits = self.request.get_tensor("logits").data
            past_key_values = tuple(
                self.request.get_tensor(key).data
                for key in self.key_value_output_names)
            past_key_values = {
                k: v
                for k, v in zip(self.key_value_input_names, past_key_values)
            }
            next_token = sample_next_token(logits[0, -1],
                                                top_k=top_k,
                                                top_p=top_p,
                                                temperature=temperature)
            output_tokens += [next_token]
            if next_token == self.eos_token_id or len(
                    output_tokens) > max_generated_tokens:
                break
            input_ids = np.array([[next_token]], dtype=np.longlong)

            yield process_response(self.tokenizer.decode(output_tokens))
        return process_response(self.tokenizer.decode(output_tokens))