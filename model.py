import re
import numpy as np
from transformers import AutoTokenizer
from openvino.runtime import Core, Tensor

# input & output names
past_names = [
    f"past_key_values.{i}.{name}" for i in range(28)
    for name in ["key", "value"]
]
present_names = [
    f"present_key_values.{i}.{name}" for i in range(28)
    for name in ["key", "value"]
]

def build_inputs(history: list[tuple[str, str]], query: str, system: str = ""):
    prompt = "{}\n".format(system)
    for i, (old_query, response) in enumerate(history):
        prompt += "[Round {}]\n问：{}\n答：{}\n".format(i + 1, old_query, response)
    prompt += "[Round {}]\n问：{}\n答：".format(len(history) + 1, query)
    print(prompt)
    return prompt


def process_response(response: str):
    response = response.strip()
    response = response.replace("[[训练时间]]", "2023年")
    punkts = [
        [",", "，"],
        ["!", "！"],
        [":", "："],
        [";", "；"],
        ["\?", "？"],
    ]
    for item in punkts:
        response = re.sub(r"([\u4e00-\u9fff])%s" % item[0], r"\1%s" % item[1],
                          response)
        response = re.sub(r"%s([\u4e00-\u9fff])" % item[0], r"%s\1" % item[1],
                          response)
    return response


class ChatGLMModel():

    def __init__(
        self,
        tokenizer_path,
        device='CPU',
        model_path='/home/ethan/intel/chatglm.openvino/ir_model/chatglm2.xml'
    ) -> None:
        self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_path,
                                                       trust_remote_code=True)
        core = Core()

        print(" --- reading model --- ")
        # read the model and corresponding weights from file
        self.model = core.read_model(model_path)

        print(" --- model compiling --- ")
        # compile the model for CPU devices
        self.request = core.compile_model(
            model=self.model, device_name=device).create_infer_request()
        self.eos_token_id = self.tokenizer.eos_token_id

    def sample_next_token(self,
                          logits: np.ndarray,
                          top_k=20,
                          top_p=0.7,
                          temperature=1):
        # softmax with temperature
        exp_logits = np.exp(logits / temperature)
        probs = exp_logits / np.sum(exp_logits)

        # top k
        top_k_idx = np.argsort(-probs)[:top_k]
        top_k_probs = probs[top_k_idx]

        # top p
        cumsum_probs = np.cumsum(top_k_probs)
        top_k_probs[(cumsum_probs - top_k_probs) > top_p] = 0.0
        top_k_probs = top_k_probs / np.sum(top_k_probs)

        # sample
        next_token = np.random.choice(top_k_idx, size=1, p=top_k_probs)
        return next_token[0].item()

    def generate_sequence(self,
                          prompt: str,
                          max_generated_tokens=100,
                          top_k=20,
                          top_p=0.7,
                          temperature=1):
        tokens = self.tokenizer([prompt], return_tensors="np")
        input_ids = tokens['input_ids']
        position_ids = tokens['position_ids']
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
                for input_name in past_names:
                    model_inputs = self.model.input(input_name)
                    shape = model_inputs.get_partial_shape()
                    if shape[0].is_dynamic:
                        shape[0] = 0
                    if shape[1].is_dynamic:
                        shape[1] = shape_input_ids[0]
                    inputs[input_name] = Tensor(
                        model_inputs.get_element_type(), shape.get_shape())

            self.request.start_async(inputs, shared_memory=True)
            self.request.wait()
            num_iteration += 1
            logits = self.request.get_tensor("logits").data
            past_key_values = tuple(
                self.request.get_tensor(key).data for key in present_names)
            past_key_values = {
                k: v
                for k, v in zip(past_names, past_key_values)
            }

            next_token = self.sample_next_token(logits[0, -1],
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
                         prompt: str,
                         max_generated_tokens,
                         top_k=20,
                         top_p=0.7,
                         temperature=1):
        tokens = self.tokenizer([prompt], return_tensors="np")
        input_ids = tokens['input_ids']
        position_ids = tokens['position_ids']
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
                for input_name in past_names:
                    model_inputs = self.model.input(input_name)
                    shape = model_inputs.get_partial_shape()
                    if shape[0].is_dynamic:
                        shape[0] = 0
                    if shape[1].is_dynamic:
                        shape[1] = shape_input_ids[0]
                    inputs[input_name] = Tensor(
                        model_inputs.get_element_type(), shape.get_shape())

            self.request.start_async(inputs, shared_memory=True)
            self.request.wait()
            logits = self.request.get_tensor("logits").data
            past_key_values = tuple(
                self.request.get_tensor(key).data for key in present_names)
            past_key_values = {
                k: v
                for k, v in zip(past_names, past_key_values)
            }
            next_token = self.sample_next_token(logits[0, -1],
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